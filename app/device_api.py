import secrets
import asyncio
import hmac
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api import bearer, current_user, require_project_access
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.device_events import device_event_hub
from app.device_presence import device_event_secret, heartbeat_state, parse_event_time
from app.emqx import EMQXError, get_emqx
from app.models import Device, DeviceTopic, Organization, OrganizationMember, Project, User
from app.schemas import DeviceCreate, DeviceCredentialView, DeviceTopicCreate, DeviceTopicView, DeviceUpdate, DeviceView
from app.security import decode_access_token_with_version, hash_password

router = APIRouter(prefix="/api/v1")


def require_project(db: Session, user: User, organization_id: int, project_id: int, permission: str) -> tuple[Organization, Project]:
    project = require_project_access(db, user, organization_id, project_id, permission)
    organization = db.get(Organization, organization_id)
    return organization, project


def require_device(db: Session, user: User, device_id: int, permission: str) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    require_project_access(db, user, device.project.organization_id, device.project_id, permission)
    return device


def device_topic_prefix(device: Device) -> str:
    return f"{device.project.organization.slug}/{device.project.slug}/{device.topic_name}/{device.client_id}/"


def make_device_topic_name(name: str, fallback: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_-")[:80] or fallback[:80]


def parse_listener_port(sockname: object) -> int | None:
    if isinstance(sockname, bool):
        return None
    if isinstance(sockname, int):
        return sockname if 1 <= sockname <= 65535 else None
    if isinstance(sockname, dict):
        for key in ("port", "listen_port"):
            if key in sockname:
                port = parse_listener_port(sockname[key])
                if port is not None:
                    return port
        return None
    if isinstance(sockname, (list, tuple)):
        for item in reversed(sockname):
            port = parse_listener_port(item)
            if port is not None:
                return port
        return None
    if isinstance(sockname, str):
        value = sockname.strip()
        if value.isdecimal():
            return parse_listener_port(int(value))
        match = re.search(r":(\d{1,5})\s*\]?\s*$", value)
        if match:
            return parse_listener_port(int(match.group(1)))
        try:
            return parse_listener_port(json.loads(value))
        except (ValueError, TypeError):
            return None
    return None


def connection_tls_for_port(port: int | None) -> bool | None:
    if port is None:
        return None
    settings = get_settings()
    if port == settings.emqx_mqtt_public_tls_port:
        return True
    if port == (settings.emqx_mqtt_public_port or settings.emqx_mqtt_port):
        return False
    return None


def topic_rules(device: Device) -> list[dict]:
    return [
        {"topic": entry.topic, "action": entry.action, "permission": "allow", "qos": entry.qos, "retain": entry.retain}
        for entry in device.topics
    ]


def device_view(device: Device, status: str | None = None) -> DeviceView:
    if status is None:
        status = "online" if device.is_active and device.broker_connected else "offline"
    view = DeviceView.model_validate(device)
    return view.model_copy(update={
        "status": status,
        "heartbeat_status": heartbeat_state(device.last_heartbeat_at, get_settings().device_heartbeat_timeout_seconds),
        "heartbeat_timeout_seconds": get_settings().device_heartbeat_timeout_seconds,
        "last_connection_tls": device.last_connection_tls if device.last_connection_tls is not None else connection_tls_for_port(device.last_connection_port),
        "last_seen_at": device.last_seen_at or device.last_heartbeat_at or (device.connection_event_at if device.broker_connected else None),
    })


def emqx_http_error(exc: EMQXError) -> HTTPException:
    status_code = 409 if "returned 409" in str(exc) else 503
    return HTTPException(status_code=status_code, detail=str(exc))


def sync_rules(device: Device) -> None:
    get_emqx().set_device_rules(device.client_id, topic_rules(device))


def ensure_device_monitoring() -> None:
    settings = get_settings()
    get_emqx().ensure_device_monitoring(settings.device_event_webhook_url, device_event_secret())


@router.get("/organizations/{organization_id}/projects/{project_id}/devices", response_model=list[DeviceView])
def list_devices(organization_id: int, project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_project(db, user, organization_id, project_id, "devices:read")
    devices = db.scalars(select(Device).where(Device.project_id == project_id).order_by(Device.name)).all()
    try:
        ensure_device_monitoring()
        session_details = get_emqx().connected_client_details([device.client_id for device in devices])
        connected_ids = set(session_details)
    except EMQXError:
        return [device_view(device, "unknown") for device in devices]
    now = datetime.now(timezone.utc)
    result = []
    changed_devices: list[tuple[Device, bool]] = []
    for device in devices:
        is_online = device.is_active and device.client_id in connected_ids
        state_changed = device.broker_connected != is_online
        detail_changed = False
        if is_online:
            session = session_details.get(device.client_id, {})
            listener_port = parse_listener_port(session.get("bind"))
            listener_tls = session.get("tls")
            if listener_port is not None and device.last_connection_port != listener_port:
                device.last_connection_port = listener_port
                detail_changed = True
            if isinstance(listener_tls, bool) and device.last_connection_tls != listener_tls:
                device.last_connection_tls = listener_tls
                detail_changed = True
        if state_changed:
            device.broker_connected = is_online
            device.connection_event_at = now
            if is_online and (device.last_seen_at is None or now > device.last_seen_at):
                device.last_seen_at = now
        if state_changed or detail_changed:
            changed_devices.append((device, state_changed))
        result.append(device_view(device, "online" if is_online else "offline"))
    if changed_devices:
        db.commit()
        for device, state_changed in changed_devices:
            device_event_hub.publish(project_id, status_event_data(device, list_changed=state_changed))
    return result


def status_event_data(device: Device, status: str | None = None, list_changed: bool = False) -> dict:
    settings = get_settings()
    resolved_status = status or ("online" if device.is_active and device.broker_connected else "offline")
    resolved_heartbeat_status = heartbeat_state(device.last_heartbeat_at, settings.device_heartbeat_timeout_seconds)
    last_seen_at = device.last_seen_at or device.last_heartbeat_at or (device.connection_event_at if device.broker_connected else None)
    return {
        "id": device.id,
        "name": device.name,
        "topic_name": device.topic_name,
        "client_id": device.client_id,
        "project_id": device.project_id,
        "project_name": device.project.name,
        "project_slug": device.project.slug,
        "organization_id": device.project.organization_id,
        "organization_name": device.project.organization.name,
        "organization_slug": device.project.organization.slug,
        "status": resolved_status,
        "list_changed": list_changed,
        "heartbeat_status": resolved_heartbeat_status,
        "heartbeat_timeout_seconds": settings.device_heartbeat_timeout_seconds,
        "last_connection_port": device.last_connection_port,
        "last_connection_tls": device.last_connection_tls if device.last_connection_tls is not None else connection_tls_for_port(device.last_connection_port),
        "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
    }


def accessible_project_ids(db: Session, user: User) -> list[int]:
    if user.is_platform_admin or user.is_platform_auditor:
        return list(db.scalars(select(Project.id).order_by(Project.id)).all())
    project_ids = []
    memberships = db.scalars(select(OrganizationMember).where(OrganizationMember.user_id == user.id)).all()
    for membership in memberships:
        projects = db.scalars(select(Project).where(Project.organization_id == membership.organization_id)).all()
        for project in projects:
            try:
                require_project_access(db, user, membership.organization_id, project.id, "devices:read")
            except HTTPException:
                continue
            project_ids.append(project.id)
    return project_ids


def validate_emqx_event_secret(value: str | None) -> None:
    if not value or not hmac.compare_digest(value, device_event_secret()):
        raise HTTPException(status_code=401, detail="Invalid EMQX event signature")


@router.post("/internal/emqx/client-event/{event_type}", status_code=204)
def receive_client_event(
    event_type: str,
    payload: dict,
    event_secret: str | None = Header(default=None, alias="x-nbu-device-event-secret"),
    db: Session = Depends(get_db),
):
    validate_emqx_event_secret(event_secret)
    if event_type not in {"connected", "disconnected"}:
        raise HTTPException(status_code=404, detail="Unknown client event")
    client_id = payload.get("clientid")
    if not isinstance(client_id, str) or not client_id:
        raise HTTPException(status_code=422, detail="Missing clientid")
    device = db.scalar(select(Device).where(Device.client_id == client_id))
    if device is None:
        return
    occurred_at = parse_event_time(payload.get("timestamp") or payload.get("disconnected_at") or payload.get("connected_at"))
    if device.connection_event_at and occurred_at < device.connection_event_at:
        return
    is_connected = event_type == "connected" and device.is_active
    changed = device.broker_connected != is_connected
    previous_port = device.last_connection_port
    device.broker_connected = is_connected
    device.connection_event_at = occurred_at
    if event_type == "connected":
        listener_port = parse_listener_port(payload.get("sockname"))
        if listener_port is not None:
            device.last_connection_port = listener_port
            device.last_connection_tls = connection_tls_for_port(listener_port)
    port_changed = device.last_connection_port != previous_port
    if is_connected and (device.last_seen_at is None or occurred_at > device.last_seen_at):
        device.last_seen_at = occurred_at
    if changed or port_changed:
        db.commit()
        device_event_hub.publish(device.project_id, status_event_data(device, list_changed=changed))
    else:
        db.commit()


@router.post("/internal/emqx/heartbeat", status_code=204)
def receive_heartbeat(
    payload: dict,
    event_secret: str | None = Header(default=None, alias="x-nbu-device-event-secret"),
    db: Session = Depends(get_db),
):
    validate_emqx_event_secret(event_secret)
    client_id = payload.get("clientid")
    topic = payload.get("topic")
    if not isinstance(client_id, str) or not isinstance(topic, str):
        raise HTTPException(status_code=422, detail="Missing clientid or topic")
    device = db.scalar(select(Device).where(Device.client_id == client_id))
    if device is None:
        return
    telemetry_root = device_topic_prefix(device) + "telemetry"
    if topic != telemetry_root and not topic.startswith(telemetry_root + "/"):
        return
    occurred_at = parse_event_time(payload.get("timestamp"))
    if device.last_heartbeat_at and occurred_at <= device.last_heartbeat_at:
        return
    device.last_heartbeat_at = occurred_at
    if device.last_seen_at is None or occurred_at > device.last_seen_at:
        device.last_seen_at = occurred_at
    db.commit()
    device_event_hub.publish(device.project_id, status_event_data(device), heartbeat=True)



@router.get("/organizations/{organization_id}/projects/{project_id}/devices/events")
async def device_status_events(
    organization_id: int,
    project_id: int,
    credentials=Depends(bearer),
):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id, token_version = decode_access_token_with_version(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from exc

    subscriber = None
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is None or not user.is_active or user.token_version != token_version:
                raise HTTPException(status_code=401, detail="User account is unavailable")
            require_project_access(db, user, organization_id, project_id, "devices:read")
            subscriber = device_event_hub.subscribe(project_id)
            devices = db.scalars(select(Device).where(Device.project_id == project_id).order_by(Device.name)).all()
            snapshot = [status_event_data(device) for device in devices]
    except Exception:
        if subscriber is not None:
            device_event_hub.unsubscribe(project_id, subscriber)
        raise

    async def stream():
        try:
            yield "event: snapshot\ndata: " + json.dumps(snapshot, separators=(",", ":")) + "\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(subscriber[1].get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                event_name = event.get("event_type", "device_status")
                yield f"event: {event_name}\ndata: " + json.dumps(event, separators=(",", ":")) + "\n\n"
        finally:
            device_event_hub.unsubscribe(project_id, subscriber)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/devices/online/events")
async def online_device_events(credentials=Depends(bearer)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id, token_version = decode_access_token_with_version(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from exc

    subscribers = []
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is None or not user.is_active or user.token_version != token_version:
                raise HTTPException(status_code=401, detail="User account is unavailable")
            project_ids = accessible_project_ids(db, user)
            subscribers = [(project_id, device_event_hub.subscribe(project_id, connection_only=True)) for project_id in project_ids]
            snapshot = {"ready": True}
    except Exception:
        for project_id, subscriber in subscribers:
            device_event_hub.unsubscribe(project_id, subscriber)
        raise

    async def stream():
        pending = {asyncio.create_task(subscriber[1].get()): subscriber for _, subscriber in subscribers}
        try:
            yield "event: snapshot\ndata: " + json.dumps(snapshot, separators=(",", ":")) + "\n\n"
            while True:
                if not pending:
                    await asyncio.sleep(15)
                    yield ": keepalive\n\n"
                    continue
                done, _ = await asyncio.wait(pending.keys(), timeout=15, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    yield ": keepalive\n\n"
                    continue
                for task in done:
                    subscriber = pending.pop(task)
                    event = task.result()
                    pending[asyncio.create_task(subscriber[1].get())] = subscriber
                    yield "event: device_status\ndata: " + json.dumps(event, separators=(",", ":")) + "\n\n"
        finally:
            for task in pending.keys():
                task.cancel()
            if pending:
                await asyncio.gather(*pending.keys(), return_exceptions=True)
            for project_id, subscriber in subscribers:
                device_event_hub.unsubscribe(project_id, subscriber)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/devices/online")
def list_online_devices(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=160),
    organization_id: int | None = Query(default=None, ge=1),
    project_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    project_ids = accessible_project_ids(db, user)
    if not project_ids:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    filters = [Device.project_id.in_(project_ids), Device.is_active.is_(True), Device.broker_connected.is_(True)]
    if organization_id is not None:
        filters.append(Project.organization_id == organization_id)
    if project_id is not None:
        filters.append(Device.project_id == project_id)
    query_text = (search or "").strip()
    if query_text:
        pattern = f"%{query_text}%"
        filters.append(or_(Device.name.ilike(pattern), Device.client_id.ilike(pattern)))

    total = db.scalar(select(func.count(Device.id)).join(Project, Project.id == Device.project_id).where(*filters)) or 0
    rows = db.scalars(
        select(Device)
        .options(joinedload(Device.project).joinedload(Project.organization))
        .join(Project, Project.id == Device.project_id)
        .where(*filters)
        .order_by(Device.name, Device.client_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": [status_event_data(device) for device in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/topics/count")
def count_topic_acls(db: Session = Depends(get_db), user: User = Depends(current_user)):
    project_ids = accessible_project_ids(db, user)
    if not project_ids:
        return {"total": 0, "publish": 0, "subscribe": 0}
    rows = db.execute(
        select(DeviceTopic.action, func.count(DeviceTopic.id))
        .join(Device, Device.id == DeviceTopic.device_id)
        .where(Device.project_id.in_(project_ids))
        .group_by(DeviceTopic.action)
    ).all()
    counts = {action: count for action, count in rows}
    publish = counts.get("publish", 0)
    subscribe = counts.get("subscribe", 0)
    return {"total": publish + subscribe, "publish": publish, "subscribe": subscribe}


@router.get("/mqtt/connection-info")
def mqtt_connection_info(request: Request, user: User = Depends(current_user)):
    settings = get_settings()
    public_host = settings.emqx_mqtt_public_host.strip()
    plain_port = settings.emqx_mqtt_public_port or settings.emqx_mqtt_port
    tls_port = settings.emqx_mqtt_public_tls_port
    return {
        "host": public_host or request.url.hostname or "",
        "host_is_configured": bool(public_host),
        "port": tls_port if settings.emqx_mqtt_tls_enabled else plain_port,
        "plain_port": plain_port,
        "tls_port": tls_port,
        "tls_enabled": settings.emqx_mqtt_tls_enabled,
        "mqtt_version_recommended": "3.1.1",
        "keepalive_seconds_recommended": settings.mqtt_keepalive_seconds,
    }


@router.post("/organizations/{organization_id}/projects/{project_id}/devices", response_model=DeviceCredentialView, status_code=201)
def register_device(organization_id: int, project_id: int, data: DeviceCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    organization, project = require_project(db, user, organization_id, project_id, "devices:manage")
    client_id = data.client_id or f"nbu_{project.id}_{secrets.token_hex(6)}"
    if db.scalar(select(Device.id).where(Device.client_id == client_id)):
        raise HTTPException(status_code=409, detail="Client ID is already registered")
    password = secrets.token_urlsafe(30)
    topic_name = make_device_topic_name(data.name, client_id)
    if db.scalar(select(Device.id).where(Device.project_id == project.id, Device.topic_name == topic_name)):
        raise HTTPException(status_code=409, detail="A device with the same MQTT topic name already exists in this project")
    base = f"{organization.slug}/{project.slug}/{topic_name}/{client_id}/"
    device = Device(project_id=project.id, name=data.name.strip(), topic_name=topic_name, client_id=client_id, credential_hash=hash_password(password))
    device.topics = [
        DeviceTopic(topic=base + "telemetry/#", action="publish", qos=[0, 1, 2], retain="all"),
        DeviceTopic(topic=base + "commands/#", action="subscribe", qos=[0, 1, 2], retain="all"),
    ]
    db.add(device)
    try:
        db.flush()
        broker = get_emqx()
        broker.ensure_access_control()
        ensure_device_monitoring()
        broker.create_device_credential(client_id, password)
        try:
            sync_rules(device)
        except EMQXError:
            broker.delete_device_credential(client_id)
            raise
        db.commit()
        db.refresh(device)
    except EMQXError as exc:
        db.rollback()
        raise emqx_http_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        try:
            get_emqx().remove_device_rules(client_id)
            get_emqx().delete_device_credential(client_id)
        except EMQXError:
            pass
        raise HTTPException(status_code=409, detail="Client ID or MQTT Topic Name is already registered") from exc
    return DeviceCredentialView(device=device_view(device, "offline"), username=client_id, password=password)


@router.get("/devices/{device_id}", response_model=DeviceView)
def get_device(device_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    device = require_device(db, user, device_id, "devices:read")
    try:
        ensure_device_monitoring()
        is_online = device.is_active and get_emqx().is_client_connected(device.client_id)
        status = "online" if is_online else "offline"
    except EMQXError:
        is_online = None
        status = "unknown"
    if is_online is not None and device.broker_connected != is_online:
        device.broker_connected = is_online
        device.connection_event_at = datetime.now(timezone.utc)
        if is_online and (device.last_seen_at is None or device.connection_event_at > device.last_seen_at):
            device.last_seen_at = device.connection_event_at
        db.commit()
        device_event_hub.publish(device.project_id, status_event_data(device, list_changed=True))
    return device_view(device, status)


@router.patch("/devices/{device_id}", response_model=DeviceView)
def update_device(device_id: int, data: DeviceUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    device = require_device(db, user, device_id, "devices:manage")
    new_name = data.name.strip()
    new_topic_name = make_device_topic_name(new_name, device.client_id)
    topic_name_changed = new_topic_name != device.topic_name
    if topic_name_changed and db.scalar(select(Device.id).where(
        Device.project_id == device.project_id,
        Device.topic_name == new_topic_name,
        Device.id != device.id,
    )):
        raise HTTPException(status_code=409, detail="A device with the same MQTT Topic Name already exists in this project")

    affected_devices = []
    clients_to_disconnect: set[str] = set()
    if topic_name_changed:
        old_prefix = device_topic_prefix(device)
        new_prefix = f"{device.project.organization.slug}/{device.project.slug}/{new_topic_name}/{device.client_id}/"
        affected_devices = db.scalars(
            select(Device)
            .where(Device.project_id == device.project_id)
            .options(selectinload(Device.topics))
        ).all()
        clients_to_disconnect.add(device.client_id)
        for affected_device in affected_devices:
            topic_changed = False
            for topic in affected_device.topics:
                if topic.topic.startswith(old_prefix):
                    topic.topic = new_prefix + topic.topic[len(old_prefix):]
                    topic_changed = True
            if topic_changed:
                clients_to_disconnect.add(affected_device.client_id)
        device.topic_name = new_topic_name

    device.name = new_name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A device with the same MQTT Topic Name already exists in this project") from exc

    if topic_name_changed:
        try:
            broker = get_emqx()
            broker.ensure_access_control()
            for affected_device in affected_devices:
                broker.set_device_rules(affected_device.client_id, topic_rules(affected_device))
                if affected_device.client_id in clients_to_disconnect:
                    broker.disconnect_client(affected_device.client_id)
        except EMQXError as exc:
            raise HTTPException(status_code=503, detail=f"Device name and Topic Name were saved, but project MQTT ACLs could not be fully synchronized. Retry after EMQX is available. Update device firmware to the new Topic Name. Details: {exc}") from exc
    device_event_hub.publish(device.project_id, status_event_data(device, list_changed=True))
    return device_view(device)


@router.post("/devices/{device_id}/credentials/rotate", response_model=DeviceCredentialView)
def rotate_credentials(device_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    device = require_device(db, user, device_id, "devices:manage")
    password = secrets.token_urlsafe(30)
    broker = get_emqx()
    try:
        broker.ensure_access_control()
        broker.rotate_device_credential(device.client_id, password)
        device.credential_hash = hash_password(password)
        db.commit()
        try:
            broker.disconnect_client(device.client_id)
            active_session_disconnected = True
            was_online = device.broker_connected
            device.broker_connected = False
            device.connection_event_at = datetime.now(timezone.utc)
            db.commit()
            if was_online:
                device_event_hub.publish(device.project_id, status_event_data(device, list_changed=True))
        except EMQXError:
            active_session_disconnected = False
    except EMQXError as exc:
        db.rollback()
        raise emqx_http_error(exc) from exc
    return DeviceCredentialView(device=device_view(device, "offline"), username=device.client_id, password=password, active_session_disconnected=active_session_disconnected)


@router.post("/devices/{device_id}/topics", response_model=DeviceTopicView, status_code=201)
def add_device_topic(device_id: int, data: DeviceTopicCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    device = require_device(db, user, device_id, "devices:manage")
    if any(qos not in (0, 1, 2) for qos in data.qos):
        raise HTTPException(status_code=422, detail="QoS values must be 0, 1, or 2")
    project_device_prefix = f"{device.project.organization.slug}/{device.project.slug}/"
    if not data.topic.startswith(project_device_prefix):
        raise HTTPException(status_code=422, detail="Topic ACL must target a device in the same project")
    target_path = data.topic[len(project_device_prefix):]
    target_topic_name, separator, target_path = target_path.partition("/")
    target_client_id, client_separator, topic_suffix = target_path.partition("/")
    if not separator or not client_separator or not topic_suffix or target_topic_name in {"+", "#"} or target_client_id in {"+", "#"}:
        raise HTTPException(status_code=422, detail="Topic must include a registered device name, Client ID, and topic path")
    target_device = db.scalar(select(Device).where(
        Device.project_id == device.project_id,
        Device.topic_name == target_topic_name,
    ))
    if target_device is None:
        raise HTTPException(status_code=422, detail="Topic must target a registered device name in this project")
    if target_client_id != target_device.client_id:
        raise HTTPException(status_code=422, detail="Topic Client ID must match the registered target device")
    if data.topic.endswith("/") or data.topic.startswith("$") or "//" in data.topic:
        raise HTTPException(status_code=422, detail="Topic filter is not valid for a device topic")
    levels = topic_suffix.split("/")
    if any(("#" in level and level != "#") or ("+" in level and level != "+") for level in levels):
        raise HTTPException(status_code=422, detail="MQTT wildcards must occupy a complete topic level")
    if "#" in levels[:-1]:
        raise HTTPException(status_code=422, detail="The # wildcard must be the final topic level")
    topic = DeviceTopic(device_id=device.id, topic=data.topic, action=data.action, qos=data.qos, retain=data.retain)
    db.add(topic)
    try:
        db.flush()
        get_emqx().ensure_access_control()
        sync_rules(device)
        db.commit()
        db.refresh(topic)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This topic rule already exists") from exc
    except EMQXError as exc:
        db.rollback()
        raise emqx_http_error(exc) from exc
    try:
        get_emqx().disconnect_client(device.client_id)
    except EMQXError as exc:
        raise HTTPException(status_code=503, detail="The ACL was saved, but EMQX could not disconnect the current device session. Reconnect the device to apply the new rule immediately.") from exc
    return topic


@router.delete("/devices/{device_id}/topics/{topic_id}", status_code=204)
def delete_device_topic(device_id: int, topic_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    device = require_device(db, user, device_id, "devices:manage")
    topic = db.scalar(select(DeviceTopic).where(DeviceTopic.id == topic_id, DeviceTopic.device_id == device_id))
    if topic is None:
        raise HTTPException(status_code=404, detail="Device topic rule not found")
    db.delete(topic)
    try:
        db.flush()
        get_emqx().ensure_access_control()
        sync_rules(device)
        db.commit()
    except EMQXError as exc:
        db.rollback()
        raise emqx_http_error(exc) from exc
    try:
        get_emqx().disconnect_client(device.client_id)
    except EMQXError as exc:
        raise HTTPException(status_code=503, detail="The ACL was removed, but EMQX could not disconnect the current device session. Disconnect it in EMQX to apply the new rule immediately.") from exc


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    device = require_device(db, user, device_id, "devices:manage")
    broker = get_emqx()
    try:
        broker.ensure_access_control()
        broker.disconnect_client(device.client_id)
        broker.remove_device_rules(device.client_id)
        broker.delete_device_credential(device.client_id)
        cli_publisher_id = f"nbu_cli_pub_{device.id}"
        broker.remove_device_rules(cli_publisher_id)
        broker.delete_device_credential(cli_publisher_id)
        command_publisher_id = f"nbu_cmd_pub_{device.id}"
        broker.remove_device_rules(command_publisher_id)
        broker.delete_device_credential(command_publisher_id)
    except EMQXError as exc:
        raise emqx_http_error(exc) from exc
    project_id = device.project_id
    was_online = device.broker_connected
    offline_event = status_event_data(device, "offline", list_changed=was_online)
    db.delete(device)
    db.commit()
    if was_online:
        device_event_hub.publish(project_id, offline_event)
