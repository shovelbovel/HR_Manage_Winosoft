from app.core import security
from app.core.config import get_settings
from app.services.auth_service import GENERIC_AUTH_ERROR
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Se connecter" in response.text


def test_login_success_sets_cookie_and_redirects(client, seeded_admin):
    settings = get_settings()
    response = client.post(
        "/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"

    access_token = response.cookies.get(settings.cookie_name)
    assert access_token is not None

    payload = security.decode_token(access_token, expected_type="access", settings=settings)
    assert payload.sub == seeded_admin.id
    assert payload.role.value == "admin"


def test_login_wrong_password_generic_error(client, seeded_admin):
    response = client.post("/login", data={"email": ADMIN_EMAIL, "password": "wrong-password"})
    assert response.status_code == 401
    assert GENERIC_AUTH_ERROR in response.text


def test_login_unknown_email_same_generic_error(client):
    response = client.post(
        "/login", data={"email": "nobody@hr-management-test.dev", "password": "whatever-123"}
    )
    assert response.status_code == 401
    assert GENERIC_AUTH_ERROR in response.text


def test_dashboard_requires_auth(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 401


def test_dashboard_with_valid_cookie(client, seeded_admin):
    settings = get_settings()
    login_response = client.post(
        "/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    access_token = login_response.cookies.get(settings.cookie_name)

    client.cookies.set(settings.cookie_name, access_token)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert ADMIN_EMAIL in response.text


def test_lockout_after_5_failed_attempts(client, seeded_admin):
    for _ in range(5):
        response = client.post(
            "/login", data={"email": ADMIN_EMAIL, "password": "wrong-password"}
        )
        assert response.status_code == 401

    # A 6th attempt with the CORRECT password is still rejected while locked.
    response = client.post("/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 401
    assert GENERIC_AUTH_ERROR in response.text
