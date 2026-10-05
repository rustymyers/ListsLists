import os
from pathlib import Path

TEST_DB = Path("/tmp/listslists-test.db")
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ.update({
    "LISTSLISTS_ENVIRONMENT": "test",
    "LISTSLISTS_DATABASE_URL": f"sqlite:///{TEST_DB}",
    "LISTSLISTS_SECRET_KEY": "test-secret-key-with-enough-entropy",
    "LISTSLISTS_BOOTSTRAP_ADMIN_PASSWORD": "test-password-123!",
    "LISTSLISTS_BOOTSTRAP_ADMIN_EMAIL": "admin@example.com",
})

import pytest
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import User
from app.security import hash_password


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(User(username="admin", email="admin@example.com", password_hash=hash_password("test-password-123!"), is_admin=True))
        db.add(User(username="viewer", email="viewer@example.com", password_hash=hash_password("viewer-password-123!")))
        db.commit()
    yield


@pytest.fixture
def client():
    with TestClient(app, base_url="https://testserver") as value:
        yield value


def auth(client, username="admin", password="test-password-123!"):
    response = client.post("/api/v1/auth/token", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return auth(client)


@pytest.fixture
def viewer_headers(client):
    return auth(client, "viewer", "viewer-password-123!")
