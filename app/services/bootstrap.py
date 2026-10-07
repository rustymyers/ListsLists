from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User
from app.security import hash_password


def bootstrap_admin(db: Session, settings: Settings) -> None:
    if db.scalar(select(func.count()).select_from(User)):
        return
    password = settings.bootstrap_admin_password
    if not password:
        raise RuntimeError(
            "Set LISTSLISTS_BOOTSTRAP_ADMIN_PASSWORD in the .env file before first startup"
        )
    user = User(
        username=settings.bootstrap_admin_username,
        email=str(settings.bootstrap_admin_email),
        password_hash=hash_password(password),
        is_admin=True,
    )
    db.add(user)
    db.commit()
