from types import SimpleNamespace

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.routers import api


def test_parent_share_does_not_expose_private_child(client, admin_headers, viewer_headers):
    child = client.post("/api/v1/lists", headers=admin_headers, json={"name": "Private child"}).json()
    parent = client.post("/api/v1/lists", headers=admin_headers, json={"name": "Shared parent", "visibility": "shared"}).json()
    client.post(f"/api/v1/lists/{child['id']}/items", headers=admin_headers, json={"name": "Secret item"})
    client.post(f"/api/v1/lists/{parent['id']}/items", headers=admin_headers, json={"name": "Nested", "referenced_list_id": child["id"]})
    with SessionLocal() as db:
        viewer_id = db.scalar(select(User.id).where(User.username == "viewer"))
    grant = client.put(f"/api/v1/lists/{parent['id']}/shares", headers=admin_headers, json={"user_id": viewer_id, "role": "viewer"})
    assert grant.status_code == 201
    response = client.post(f"/api/v1/lists/{parent['id']}/resolve", headers=viewer_headers, json={})
    assert response.status_code == 403
    client.put(f"/api/v1/lists/{child['id']}/shares", headers=admin_headers, json={"user_id": viewer_id, "role": "viewer"})
    response = client.post(f"/api/v1/lists/{parent['id']}/resolve", headers=viewer_headers, json={})
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Secret item"


def test_unchanged_share_does_not_resend_invitation(client, admin_headers, monkeypatch):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Shared list"}
    ).json()
    with SessionLocal() as db:
        viewer_id = db.scalar(select(User.id).where(User.username == "viewer"))
    sent_to = []
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(smtp_host="smtp.example.com", public_base_url="https://example.com"),
    )
    monkeypatch.setattr(api, "send_email", lambda settings, to, subject, body: sent_to.append(to))

    for _ in range(2):
        response = client.put(
            f"/api/v1/lists/{list_data['id']}/shares",
            headers=admin_headers,
            json={"user_id": viewer_id, "role": "viewer"},
        )
        assert response.status_code == 201

    assert sent_to == ["viewer@example.com"]
