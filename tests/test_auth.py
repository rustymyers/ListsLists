def test_token_rejects_bad_password(client):
    response = client.post("/api/v1/auth/token", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401


def test_protected_route_requires_auth(client):
    assert client.get("/api/v1/lists").status_code == 401
