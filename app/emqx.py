from functools import lru_cache
from threading import Lock
from urllib.parse import quote

import httpx

from app.config import get_settings

AUTHENTICATOR_ID = "password_based:built_in_database"
AUTHENTICATOR_PATH = quote(AUTHENTICATOR_ID, safe="")
AUTHZ_TYPE = "built_in_database"


class EMQXError(Exception):
    pass


class EMQXClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.emqx_base_url.rstrip("/")
        self.username = settings.emqx_username
        self.password = settings.emqx_password
        self.client = httpx.Client(base_url=self.base_url, timeout=settings.emqx_timeout_seconds)
        self._token: str | None = None
        self._token_lock = Lock()
        self._configuration_lock = Lock()
        self._configured = False
        self._monitoring_configured = False

    def _login(self, force: bool = False) -> str:
        with self._token_lock:
            if self._token and not force:
                return self._token
            if not self.password:
                raise EMQXError("EMQX_PASSWORD is not configured")
            try:
                response = self.client.post("/api/v5/login", json={"username": self.username, "password": self.password})
                response.raise_for_status()
                self._token = response.json()["token"]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                self._token = None
                raise EMQXError("Could not authenticate with the EMQX REST API; check EMQX_BASE_URL, EMQX_USERNAME, and EMQX_PASSWORD") from exc
            return self._token

    def request(self, method: str, path: str, *, json: object | None = None, params: dict | None = None, allow_not_found: bool = False) -> object | None:
        for attempt in range(2):
            token = self._login(force=attempt == 1)
            try:
                response = self.client.request(method, path, json=json, params=params, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            except httpx.HTTPError as exc:
                raise EMQXError("EMQX REST API is unavailable") from exc
            if response.status_code == 401 and attempt == 0:
                with self._token_lock:
                    self._token = None
                continue
            if allow_not_found and response.status_code == 404:
                return None
            if response.is_error:
                if response.status_code >= 500:
                    detail = "EMQX returned a server error"
                else:
                    try:
                        payload = response.json()
                        detail = str(payload.get("message") or payload.get("reason") or payload.get("code") or "request rejected")
                    except ValueError:
                        detail = "request rejected"
                raise EMQXError(f"EMQX REST API returned {response.status_code}: {detail}")
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        raise EMQXError("EMQX REST API authentication expired")

    @staticmethod
    def _items(payload: object, key: str | None = None) -> list[dict]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            values = payload.get(key) if key else None
            if values is None:
                values = payload.get("data")
            return values if isinstance(values, list) else []
        return []

    def ensure_access_control(self) -> None:
        if self._configured:
            return
        with self._configuration_lock:
            if self._configured:
                return
            auth_rows = self._items(self.request("GET", "/api/v5/authentication"))
            auth = next((row for row in auth_rows if row.get("id") == AUTHENTICATOR_ID), None)
            if auth is None:
                self.request("POST", "/api/v5/authentication", json={
                    "mechanism": "password_based",
                    "backend": "built_in_database",
                    "enable": True,
                    "user_id_type": "clientid",
                    "password_hash_algorithm": {"name": "sha256", "salt_position": "suffix"},
                })
            else:
                detail = self.request("GET", f"/api/v5/authentication/{AUTHENTICATOR_PATH}")
                if isinstance(detail, dict) and detail.get("user_id_type") not in (None, "clientid"):
                    # Keep the broker's existing hash and optional configuration: replacing the
                    # authenticator would invalidate users and may discard unrelated settings.
                    preserved_keys = (
                        "mechanism", "backend", "enable", "password_hash_algorithm",
                        "bootstrap_file", "bootstrap_type", "precondition",
                    )
                    config = {key: detail[key] for key in preserved_keys if key in detail}
                    config["user_id_type"] = "clientid"
                    try:
                        self.request("PUT", f"/api/v5/authentication/{AUTHENTICATOR_PATH}", json=config)
                    except EMQXError as exc:
                        raise EMQXError(
                            "Could not switch the existing EMQX built-in authenticator to clientid. "
                            "Check that the EMQX API user can update authentication settings. "
                            f"Details: {exc}"
                        ) from exc
                    updated = self.request("GET", f"/api/v5/authentication/{AUTHENTICATOR_PATH}")
                    if not isinstance(updated, dict) or updated.get("user_id_type") != "clientid":
                        raise EMQXError("EMQX did not apply User ID Type=clientid to the built-in authenticator")
                if isinstance(detail, dict) and detail.get("enable") is False:
                    raise EMQXError("The existing EMQX built-in authenticator is disabled. Enable it before managing platform devices.")
            self.request("PUT", f"/api/v5/authentication/{AUTHENTICATOR_PATH}/position/front")

            sources_payload = self.request("GET", "/api/v5/authorization/sources")
            sources = self._items(sources_payload, "sources")
            authz_source = next((source for source in sources if source.get("type") == AUTHZ_TYPE), None)
            if authz_source is None:
                self.request("POST", "/api/v5/authorization/sources", json={"type": AUTHZ_TYPE, "enable": True, "max_rules": 100})
            elif authz_source.get("enable") is False:
                raise EMQXError("The existing EMQX built-in authorization source is disabled. Enable it before managing platform devices.")
            self.request("POST", f"/api/v5/authorization/sources/{AUTHZ_TYPE}/move", json={"position": "front"})
            self._configured = True

    def ensure_device_monitoring(self, webhook_url: str, event_secret: str) -> None:
        if self._monitoring_configured:
            return
        with self._configuration_lock:
            if self._monitoring_configured:
                return
            self._ensure_device_monitoring(webhook_url, event_secret)
            self._monitoring_configured = True

    def _ensure_device_monitoring(self, webhook_url: str, event_secret: str) -> None:
        connector_name = "nbu_platform_device_events"
        connector_id = f"http:{connector_name}"
        connector_rows = self._items(self.request("GET", "/api/v5/connectors"))
        if not any(
            row.get("id") == connector_id
            or (row.get("type") == "http" and row.get("name") == connector_name)
            for row in connector_rows
        ):
            self.request("POST", "/api/v5/connectors", json={
                "name": connector_name,
                "type": "http",
                "url": webhook_url.rstrip("/"),
                "connect_timeout": "5s",
                "pool_size": 8,
                "enable": True,
                "headers": {"content-type": "application/json"},
            })

        actions = [
            ("nbu_platform_client_connected", "/api/v1/internal/emqx/client-event/connected"),
            ("nbu_platform_client_disconnected", "/api/v1/internal/emqx/client-event/disconnected"),
            ("nbu_platform_heartbeat", "/api/v1/internal/emqx/heartbeat"),
        ]
        action_rows = self._items(self.request("GET", "/api/v5/actions"))
        for action_name, path in actions:
            action_id = f"http:{action_name}"
            action_config = {
                "name": action_name,
                "type": "http",
                "connector": connector_name,
                "enable": True,
                "parameters": {
                    "path": path,
                    "method": "post",
                    "body": "\x24{.}",
                    "headers": {
                        "content-type": "application/json",
                        "x-nbu-device-event-secret": event_secret,
                    },
                },
                "resource_opts": {
                    "query_mode": "async",
                    "worker_pool_size": 8,
                    "health_check_interval": "15s",
                },
            }
            if any(
                row.get("id") == action_id
                or (row.get("type") == "http" and row.get("name") == action_name)
                for row in action_rows
            ):
                update_config = {key: value for key, value in action_config.items() if key not in {"name", "type"}}
                self.request("PUT", f"/api/v5/actions/{quote(action_id, safe='')}", json=update_config)
            else:
                self.request("POST", "/api/v5/actions", json=action_config)

        rule_configs = [
            {
                "id": "nbu_platform_client_connected",
                "name": "NBU Platform client connected",
                "sql": 'SELECT clientid, sockname, connected_at, timestamp FROM "$events/client_connected"',
                "actions": ["http:nbu_platform_client_connected"],
            },
            {
                "id": "nbu_platform_client_disconnected",
                "name": "NBU Platform client disconnected",
                "sql": 'SELECT clientid, connected_at, disconnected_at, timestamp, reason FROM "$events/client_disconnected"',
                "actions": ["http:nbu_platform_client_disconnected"],
            },
            {
                "id": "nbu_platform_device_heartbeat",
                "name": "NBU Platform device telemetry heartbeat",
                "sql": 'SELECT clientid, topic, timestamp FROM "+/+/+/+/telemetry/#"',
                "actions": ["http:nbu_platform_heartbeat"],
            },
        ]
        rule_rows = self._items(self.request("GET", "/api/v5/rules"))
        for rule in rule_configs:
            rule["enable"] = True
            rule["description"] = "Managed by NBU IoT Platform"
            if any(row.get("id") == rule["id"] for row in rule_rows):
                self.request("PUT", f"/api/v5/rules/{quote(rule['id'], safe='')}", json=rule)
            else:
                self.request("POST", "/api/v5/rules", json=rule)

    def create_device_credential(self, client_id: str, password: str) -> None:
        self.request("POST", f"/api/v5/authentication/{AUTHENTICATOR_PATH}/users", json={"user_id": client_id, "password": password, "is_superuser": False})

    def rotate_device_credential(self, client_id: str, password: str) -> None:
        self.request("PUT", f"/api/v5/authentication/{AUTHENTICATOR_PATH}/users/{quote(client_id, safe='')}", json={"password": password, "is_superuser": False})

    def set_device_rules(self, client_id: str, rules: list[dict]) -> None:
        safe_rules = [*rules, {"action": "all", "permission": "deny", "topic": "#"}]
        self.request("PUT", f"/api/v5/authorization/sources/{AUTHZ_TYPE}/rules/clients/{quote(client_id, safe='')}", json={"clientid": client_id, "rules": safe_rules})

    def remove_device_rules(self, client_id: str) -> None:
        self.request("DELETE", f"/api/v5/authorization/sources/{AUTHZ_TYPE}/rules/clients/{quote(client_id, safe='')}", allow_not_found=True)

    def delete_device_credential(self, client_id: str) -> None:
        self.request("DELETE", f"/api/v5/authentication/{AUTHENTICATOR_PATH}/users/{quote(client_id, safe='')}", allow_not_found=True)

    def disconnect_client(self, client_id: str) -> None:
        self.request("DELETE", f"/api/v5/clients/{quote(client_id, safe='')}", allow_not_found=True)

    def connected_client_ids(self, client_ids: list[str]) -> set[str]:
        # Read each registered client's live session directly. This avoids broad
        # client-list pagination and persistent/offline sessions being mistaken
        # for active connections.
        return {client_id for client_id in dict.fromkeys(client_ids) if self.is_client_connected(client_id)}

    def connected_client_details(self, client_ids: list[str]) -> dict[str, dict]:
        sessions: dict[str, dict] = {}
        for client_id in dict.fromkeys(client_ids):
            payload = self.request("GET", f"/api/v5/clients/{quote(client_id, safe='')}", allow_not_found=True)
            if not isinstance(payload, dict):
                continue
            state = payload.get("conn_state")
            connected = state == "connected" if state is not None else payload.get("connected") is True
            listener_id = payload.get("listener")
            if connected and isinstance(listener_id, str):
                sessions[client_id] = {"listener": listener_id}

        if not sessions:
            return sessions
        try:
            payload = self.request("GET", "/api/v5/listeners")
        except EMQXError:
            payload = []
        listeners = self._items(payload)
        by_id = {item.get("id"): item for item in listeners if isinstance(item.get("id"), str)}
        for detail in sessions.values():
            listener = by_id.get(detail["listener"], {})
            detail["bind"] = listener.get("bind")
            listener_type = listener.get("type") or detail["listener"].partition(":")[0]
            detail["tls"] = listener_type in {"ssl", "wss"}
        return sessions

    def is_client_connected(self, client_id: str) -> bool:
        payload = self.request("GET", f"/api/v5/clients/{quote(client_id, safe='')}", allow_not_found=True)
        if not isinstance(payload, dict):
            return False
        state = payload.get("conn_state")
        if state is not None:
            return state == "connected"
        return payload.get("connected") is True


@lru_cache
def get_emqx() -> EMQXClient:
    return EMQXClient()
