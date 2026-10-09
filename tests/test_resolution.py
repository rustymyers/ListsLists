def create_list(client, headers, name):
    response = client.post("/api/v1/lists", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def add_item(client, headers, list_id, **values):
    data = {"name": values.pop("name", "item"), **values}
    response = client.post(f"/api/v1/lists/{list_id}/items", headers=headers, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def test_nested_resolution_and_duplicate_quantity_merge(client, admin_headers):
    component = create_list(client, admin_headers, "Component")
    parent = create_list(client, admin_headers, "Parent")
    add_item(client, admin_headers, component["id"], name="Water", quantity=2, unit="L", identity_key="water", packing_spot="Side pocket")
    add_item(client, admin_headers, component["id"], name="Water", quantity=3, unit="L", identity_key="water", packing_spot="Main compartment")
    add_item(client, admin_headers, parent["id"], name="Component x2", quantity=2, referenced_list_id=component["id"])
    response = client.post(f"/api/v1/lists/{parent['id']}/resolve", headers=admin_headers, json={"merge_duplicates": True, "combine_quantities": True})
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 1
    assert rows[0]["quantity"] == 10
    assert rows[0]["packing_spots"] == ["Side pocket", "Main compartment"]
    assert len(rows[0]["source_item_ids"]) == 2


def test_cycle_is_rejected(client, admin_headers):
    first = create_list(client, admin_headers, "First")
    second = create_list(client, admin_headers, "Second")
    add_item(client, admin_headers, first["id"], name="second", referenced_list_id=second["id"])
    response = client.post(f"/api/v1/lists/{second['id']}/items", headers=admin_headers, json={"name": "first", "referenced_list_id": first["id"]})
    assert response.status_code == 409
