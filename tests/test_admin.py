import json
import re

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ListModel, User


def test_admin_can_export_and_replace_data_without_password_hashes(client, admin_headers):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Packing"}
    ).json()
    client.post(
        f"/api/v1/lists/{list_data['id']}/items",
        headers=admin_headers,
        json={"name": "Tent", "quantity": 1, "packing_spot": "Blue bin"},
    )

    exported = client.get("/admin/data-export", headers=admin_headers)
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["format"] == "listslists-backup"
    assert payload["version"] == 1
    assert all("password_hash" not in user for user in payload["users"])
    assert payload["lists"][0]["name"] == "Packing"
    assert payload["list_items"][0]["packing_spot"] == "Blue bin"

    page = client.get("/admin", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    imported = client.post(
        "/admin/data-import",
        headers=admin_headers,
        data={"csrf_token": csrf_token, "confirmation": "REPLACE"},
        files={"backup": ("backup.json", json.dumps(payload), "application/json")},
        follow_redirects=False,
    )

    assert imported.status_code == 303
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin.password_hash is None
        assert admin.must_change_password
        assert [entry.name for entry in db.scalars(select(ListModel)).all()] == ["Packing"]


def test_admin_import_requires_replacement_confirmation(client, admin_headers):
    page = client.get("/admin", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/admin/data-import",
        headers=admin_headers,
        data={"csrf_token": csrf_token, "confirmation": "no"},
        files={"backup": ("backup.json", "{}", "application/json")},
    )

    assert response.status_code == 422
    assert "REPLACE" in response.text
