import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base
from app.models import User
from app.security import verify_password
from app.services.bootstrap import bootstrap_admin


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_bootstrap_admin_requires_configured_password(db):
    settings = Settings(_env_file=None, bootstrap_admin_password=None)

    with pytest.raises(RuntimeError, match="LISTSLISTS_BOOTSTRAP_ADMIN_PASSWORD"):
        bootstrap_admin(db, settings)

    assert db.scalar(select(User)) is None


def test_bootstrap_admin_uses_configured_password(db):
    password = "configured-initial-password"
    settings = Settings(_env_file=None, bootstrap_admin_password=password)

    bootstrap_admin(db, settings)

    admin = db.scalar(select(User))
    assert admin is not None
    assert admin.is_admin
    assert not admin.must_change_password
    assert verify_password(password, admin.password_hash)
