import re


def test_failed_login_keeps_login_form_and_username(client):
    login_page = client.get("/login")
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)

    response = client.post(
        "/login",
        data={
            "csrf_token": csrf_token,
            "username": "admin",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert '<h1>Sign in</h1>' in response.text
    assert 'name="username" value="admin"' in response.text
    assert 'name="password" type="password" required' in response.text


def test_token_rejects_bad_password(client):
    response = client.post("/api/v1/auth/token", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401


def test_protected_route_requires_auth(client):
    assert client.get("/api/v1/lists").status_code == 401
