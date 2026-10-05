import re


def test_item_reorder_copy_move_and_delete(client, admin_headers):
    one = client.post("/api/v1/lists", headers=admin_headers, json={"name": "One"}).json()
    two = client.post("/api/v1/lists", headers=admin_headers, json={"name": "Two"}).json()
    a = client.post(f"/api/v1/lists/{one['id']}/items", headers=admin_headers, json={"name": "A"}).json()
    b = client.post(f"/api/v1/lists/{one['id']}/items", headers=admin_headers, json={"name": "B"}).json()
    assert client.post(f"/api/v1/lists/{one['id']}/items/reorder", headers=admin_headers, json={"item_ids": [b["id"], a["id"]]}).status_code == 204
    copied = client.post(f"/api/v1/items/{a['id']}/copy", headers=admin_headers, json={"target_list_id": two["id"]})
    assert copied.status_code == 201
    moved = client.post(f"/api/v1/items/{b['id']}/move", headers=admin_headers, json={"target_list_id": two["id"]})
    assert moved.status_code == 200
    assert client.delete(f"/api/v1/items/{a['id']}", headers=admin_headers).status_code == 204


def test_web_add_item_returns_and_persists_item_row(client, admin_headers):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Groceries"}
    ).json()
    page = client.get(f"/l/{list_data['slug']}", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    response = client.post(
        f"/l/{list_data['slug']}/items",
        data={"name": "Milk", "csrf_token": csrf_token},
        headers={**admin_headers, "HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "<strong>Milk</strong>" in response.text
    assert "<strong>Milk</strong>" in client.get(
        f"/l/{list_data['slug']}", headers=admin_headers
    ).text


def test_web_edit_item_persists_changes(client, admin_headers):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Groceries"}
    ).json()
    item = client.post(
        f"/api/v1/lists/{list_data['id']}/items",
        headers=admin_headers,
        json={"name": "Milk"},
    ).json()
    page = client.get(f"/items/{item['id']}/edit", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    response = client.post(
        f"/items/{item['id']}/edit",
        data={
            "name": "Oat milk",
            "quantity": "2",
            "unit": "cartons",
            "tags": "breakfast, vegan",
            "csrf_token": csrf_token,
        },
        headers=admin_headers,
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = client.get(f"/api/v1/items/{item['id']}", headers=admin_headers).json()
    assert updated["name"] == "Oat milk"
    assert updated["quantity"] == 2
    assert updated["unit"] == "cartons"
    assert updated["tags"] == ["breakfast", "vegan"]


def test_web_add_required_list_and_reject_cycle(client, admin_headers):
    parent = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Parent"}
    ).json()
    child = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Child"}
    ).json()
    page = client.get(f"/l/{parent['slug']}", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    response = client.post(
        f"/l/{parent['slug']}/required-list",
        data={"referenced_list_id": child["id"], "csrf_token": csrf_token},
        headers=admin_headers,
        follow_redirects=False,
    )
    assert response.status_code == 303

    page = client.get(f"/l/{child['slug']}", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post(
        f"/l/{child['slug']}/required-list",
        data={"referenced_list_id": parent["id"], "csrf_token": csrf_token},
        headers=admin_headers,
    )
    assert response.status_code == 409
