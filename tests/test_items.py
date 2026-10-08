import re


def test_home_page_renders_lists(client, admin_headers):
    response = client.get("/", headers=admin_headers)

    assert response.status_code == 200
    assert "<h1>Your lists</h1>" in response.text
    assert 'hx-get="/"' in response.text
    assert 'hx-trigger="input changed delay:250ms, search"' in response.text


def test_home_page_search_updates_list_results(client, admin_headers):
    client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Camping equipment"}
    )
    client.post("/api/v1/lists", headers=admin_headers, json={"name": "Pantry"})

    response = client.get(
        "/",
        params={"q": "camping"},
        headers={**admin_headers, "HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'id="list-results"' in response.text
    assert "Camping equipment" in response.text
    assert "Pantry" not in response.text


def test_preview_shows_source_list_names_not_ids(client, admin_headers):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Camping"}
    ).json()
    client.post(
        f"/api/v1/lists/{list_data['id']}/items",
        headers=admin_headers,
        json={"name": "Tent"},
    )

    preview = client.get(f"/l/{list_data['slug']}/preview", headers=admin_headers)

    assert preview.status_code == 200
    assert "Camping" in preview.text
    assert list_data["id"] not in preview.text
    assert 'class="sort-header" type="button" data-sort-key="name"' in preview.text
    assert 'class="sort-header" type="button" data-sort-key="quantity"' in preview.text
    assert 'class="sort-header" type="button" data-sort-key="source-lists"' in preview.text


def test_items_page_creates_canonical_item(client, admin_headers):
    page = client.get("/items", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    response = client.post(
        "/items",
        headers=admin_headers,
        data={
            "csrf_token": csrf_token,
            "name": "Tent",
            "unit": "each",
            "category": "Shelter",
            "tags": "camping, lightweight",
            "storage_location": "Garage",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    details = client.get(response.headers["location"], headers=admin_headers)
    assert "<h1>Tent</h1>" in details.text
    assert "Shelter" in details.text
    assert "camping, lightweight" in details.text


def test_items_page_search_updates_item_results(client, admin_headers):
    for name in ("Tent", "Pan"):
        page = client.get("/items", headers=admin_headers)
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        response = client.post(
            "/items",
            headers=admin_headers,
            data={"csrf_token": csrf_token, "name": name, "unit": "each"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    response = client.get(
        "/items",
        params={"q": "tent"},
        headers={**admin_headers, "HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'id="item-results"' in response.text
    assert "Tent" in response.text
    assert "Pan" not in response.text


def test_items_page_links_to_details_and_edits_canonical_item(client, admin_headers):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Groceries"}
    ).json()
    item = client.post(
        f"/api/v1/lists/{list_data['id']}/items",
        headers=admin_headers,
        json={"name": "Milk", "unit": "carton"},
    ).json()

    page = client.get("/items", headers=admin_headers)
    assert f'href="/items/{item["canonical_item_id"]}"' in page.text

    details = client.get(f"/items/{item['canonical_item_id']}", headers=admin_headers)
    assert details.status_code == 200
    assert f'href="/canonical-items/{item["canonical_item_id"]}/edit"' in details.text
    assert f'<a href="/l/{list_data["slug"]}">{list_data["name"]}</a>' in details.text
    assert "1.0 carton" in details.text

    edit_page = client.get(
        f"/canonical-items/{item['canonical_item_id']}/edit", headers=admin_headers
    )
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', edit_page.text).group(1)
    response = client.post(
        f"/canonical-items/{item['canonical_item_id']}/edit",
        headers=admin_headers,
        data={
            "csrf_token": csrf_token,
            "name": "Oat milk",
            "unit": "carton",
            "category": "Breakfast",
            "tags": "vegan",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = client.get(f"/api/v1/items/{item['id']}", headers=admin_headers).json()
    assert updated["name"] == "Oat milk"
    assert updated["category"] == "Breakfast"
    assert updated["tags"] == ["vegan"]


def test_canonical_item_delete_blocks_used_items_and_deletes_unused_items(
    client, admin_headers
):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Groceries"}
    ).json()
    placement = client.post(
        f"/api/v1/lists/{list_data['id']}/items",
        headers=admin_headers,
        json={"name": "Milk"},
    ).json()
    details = client.get(
        f"/items/{placement['canonical_item_id']}", headers=admin_headers
    )
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', details.text).group(1)

    blocked = client.post(
        f"/canonical-items/{placement['canonical_item_id']}/delete",
        headers=admin_headers,
        data={"csrf_token": csrf_token},
    )
    assert blocked.status_code == 409
    assert "Remove those placements first." in blocked.text

    unused = client.post(
        "/api/v1/canonical-items",
        headers=admin_headers,
        json={"name": "Unused", "unit": "each"},
    ).json()
    details = client.get(f"/items/{unused['id']}", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', details.text).group(1)
    deleted = client.post(
        f"/canonical-items/{unused['id']}/delete",
        headers=admin_headers,
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/items"
    assert client.get(f"/items/{unused['id']}", headers=admin_headers).status_code == 404


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


def test_list_page_shows_drag_handles_for_editors(client, admin_headers):
    list_data = client.post(
        "/api/v1/lists", headers=admin_headers, json={"name": "Ordered"}
    ).json()
    client.post(
        f"/api/v1/lists/{list_data['id']}/items",
        headers=admin_headers,
        json={"name": "First"},
    )
    page = client.get(f"/l/{list_data['slug']}", headers=admin_headers)

    assert 'data-reorder-url="/api/v1/lists/' in page.text
    assert 'class="drag-handle"' in page.text
    assert 'class="sort-header" type="button" data-sort-key="name"' in page.text
    assert 'class="sort-header" type="button" data-sort-key="quantity"' in page.text


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
    page = client.get(f"/l/{parent['slug']}", headers=admin_headers)
    assert "<h2>Required lists</h2>" in page.text
    assert f'<a href="/l/{child["slug"]}">{child["name"]}</a>' in page.text
    assert f"<strong>{child['name']}</strong>" not in page.text
    page = client.get(f"/l/{child['slug']}", headers=admin_headers)
    assert "<h2>Required by</h2>" in page.text
    assert f'<a href="/l/{parent["slug"]}">{parent["name"]}</a>' in page.text

    page = client.get(f"/l/{child['slug']}", headers=admin_headers)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post(
        f"/l/{child['slug']}/required-list",
        data={"referenced_list_id": parent["id"], "csrf_token": csrf_token},
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert '<section class="card status-error" role="alert">' in response.text
    assert "This reference would create a circular list graph" in response.text
