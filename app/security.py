import hashlib
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, Request, status
from pwdlib import PasswordHash

from app.config import Settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    return bool(hashed and password_hasher.verify(password, hashed))


def create_access_token(user_id: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return str(payload["sub"])
    except (jwt.PyJWTError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def new_reset_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def reset_token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def request_from_trusted_proxy(request: Request, settings: Settings) -> bool:
    if not settings.trusted_proxy_cidrs:
        return False
    try:
        peer = ipaddress.ip_address(request.client.host if request.client else "")
        return any(peer in ipaddress.ip_network(cidr) for cidr in settings.trusted_proxy_cidrs)
    except ValueError:
        return False


def ensure_csrf(request: Request, submitted: str | None) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token
