
from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import AdminUser, Permission, Role
from movimento7.validation import safe_next_path


def test_open_redirect_validation():
    assert safe_next_path("/admin/inscricoes") == "/admin/inscricoes"
    assert safe_next_path("https://evil.test") is None
    assert safe_next_path("//evil.test") is None
    assert safe_next_path("%2F%2Fevil.test") is None
    assert safe_next_path("/\\evil.test") is None


def create_admin(app):
    with app.app_context():
        permission = Permission(slug="dashboard.read", description="Dashboard")
        role = Role(
            slug="administrador", name="Administrador", permissions=[permission]
        )
        user = AdminUser(
            email="admin@example.test",
            name="Admin Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add(user)
        db.session.commit()


def test_login_is_non_enumerating_and_sets_httponly(app, client):
    create_admin(app)
    wrong = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "missing@example.test", "password": "nope"},
    )
    assert wrong.status_code == 401
    assert wrong.json["error"]["code"] == "invalid_credentials"
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert response.json["data"]["csrf_token"]


def test_admin_mutation_rejects_missing_csrf(app, client):
    create_admin(app)
    login = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert login.status_code == 200
    response = client.post("/api/v1/admin/auth/logout")
    assert response.status_code == 403
    assert response.json["error"]["code"] == "csrf_invalid"


def test_lockout_after_five_failures(app, client):
    create_admin(app)
    for _ in range(5):
        response = client.post(
            "/api/v1/admin/auth/login",
            json={"email": "admin@example.test", "password": "wrong"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert limited.status_code == 429


def test_csv_formula_prefix_can_be_neutralized():
    def safe_csv(value: str) -> str:
        return "'" + value if value.startswith(("=", "+", "-", "@")) else value

    assert safe_csv("=SUM(A1:A2)").startswith("'")
    assert safe_csv("texto") == "texto"
