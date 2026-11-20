import hashlib
import hmac
from datetime import datetime, timezone

from app.config import get_settings


def device_event_secret() -> str:
    return hmac.new(
        get_settings().secret_key.encode(),
        b"nbu-iot-emqx-events-v1",
        hashlib.sha256,
    ).hexdigest()


def parse_event_time(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str):
        raw = value.strip()
        try:
            numeric = float(raw)
        except ValueError:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
            parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def heartbeat_state(last_heartbeat_at: datetime | None, timeout_seconds: int) -> str:
    if last_heartbeat_at is None:
        return "waiting"
    if last_heartbeat_at.tzinfo is None:
        last_heartbeat_at = last_heartbeat_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last_heartbeat_at).total_seconds()
    return "active" if age <= timeout_seconds else "stale"
