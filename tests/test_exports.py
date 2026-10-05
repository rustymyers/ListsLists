def test_json_and_csv_exports(client, admin_headers):
    list_obj = client.post("/api/v1/lists", headers=admin_headers, json={"name": "Exportable"}).json()
    client.post(f"/api/v1/lists/{list_obj['id']}/items", headers=admin_headers, json={"name": "Tent", "quantity": 1, "tags": ["camp"]})
    json_response = client.post(f"/api/v1/lists/{list_obj['id']}/export?format=json", headers=admin_headers, json={})
    assert json_response.status_code == 200
    assert json_response.json()["items"][0]["name"] == "Tent"
    csv_response = client.post(f"/api/v1/lists/{list_obj['id']}/export?format=csv", headers=admin_headers, json={})
    assert csv_response.status_code == 200
    assert "Tent" in csv_response.text
    assert "attachment" in csv_response.headers["content-disposition"]
