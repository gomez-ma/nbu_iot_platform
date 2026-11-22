from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "ver": token_version, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> int:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    return int(payload["sub"])


def decode_access_token_with_version(token: str) -> tuple[int, int]:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    return int(payload["sub"]), int(payload.get("ver", 0))


def decode_access_token_payload(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])


def create_support_access_token(user_id: int, token_version: int, session_id: int, actor_id: int, actor_version: int, expires_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id), "ver": token_version, "iat": now, "exp": expires_at,
        "support_session": session_id, "support_actor": actor_id, "support_actor_ver": actor_version,
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")
