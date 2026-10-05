from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import User
from app.security import decode_access_token, request_from_trusted_proxy

bearer = HTTPBearer(auto_error=False)
Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def _proxy_user(request: Request, db: Session, settings: Settings) -> User | None:
    if settings.auth_mode not in {"proxy", "both"} or not request_from_trusted_proxy(request, settings):
        return None
    username = request.headers.get(settings.proxy_user_header)
    if not username:
        return None
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if not user and settings.proxy_auto_create_users:
        email = request.headers.get(settings.proxy_email_header) or f"{username}@proxy.invalid"
        user = User(username=username, email=email, auth_source="proxy")
        db.add(user)
        db.commit()
    return user if user and user.is_active else None


def optional_user(
    request: Request,
    db: Db,
    settings: Config,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User | None:
    user = _proxy_user(request, db, settings)
    if user:
        return user
    user_id = None
    if credentials:
        user_id = decode_access_token(credentials.credentials, settings)
    elif request.session.get("user_id"):
        user_id = request.session["user_id"]
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user if user and user.is_active else None


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Password change required at /change-password")
    return user


def current_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user

CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
AdminUser = Annotated[User, Depends(current_admin)]
