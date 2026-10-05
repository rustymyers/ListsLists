import os
import secrets
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User
from app.security import hash_password


def bootstrap_admin(db: Session, settings: Settings) -> Path | None:
    if db.scalar(select(func.count()).select_from(User)):
        return None
    generated = settings.bootstrap_admin_password is None
    password = settings.bootstrap_admin_password or secrets.token_urlsafe(24)
    user = User(
        username=settings.bootstrap_admin_username,
        email=str(settings.bootstrap_admin_email),
        password_hash=hash_password(password),
        is_admin=True,
        must_change_password=generated,
    )
    db.add(user)
    db.commit()
    if not generated:
        return None
    output = settings.secrets_dir / "initial-admin.txt"
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(f"username={user.username}\npassword={password}\n")
    return output
