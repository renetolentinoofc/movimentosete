from sqlalchemy import select
from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import AdminUser, CommunicationLog, Permission, Role


def create_admin(app):
    with app.app_context():
        permission = Permission(
            slug="communications.manage", description="Administrar comunicações"
        )
        role = Role(slug="communicator", name="Comunicação", permissions=[permission])
        admin = AdminUser(
            email="admin@example.test",
            name="Administradora Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add(admin)
        db.session.commit()


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def configure_email(app, *, mode="sandbox", password="app-password-test"):
    app.config.update(
        EMAIL_DELIVERY_MODE=mode,
        EMAIL_SANDBOX_RECIPIENT="movimentosete777@gmail.com",
        EMAIL_FROM_ADDRESS="movimentosete777@gmail.com",
        EMAIL_FROM_NAME="Movimento 7",
        EMAIL_REPLY_TO="movimentosete777@gmail.com",
        SMTP_HOST="smtp.gmail.com",
        SMTP_PORT=587,
        SMTP_USERNAME="movimentosete777@gmail.com",
        SMTP_PASSWORD=password,
        SMTP_USE_TLS=True,
    )


def test_configuration_never_exposes_smtp_password(app, client):
    create_admin(app)
    configure_email(app)
    login(client)

    response = client.get("/api/v1/admin/communications")

    assert response.status_code == 200
    configuration = response.json["data"]["configuration"]
    assert configuration["configured"] is True
    assert configuration["smtp_password_set"] is True
    assert configuration["smtp_username"] == "mo**************@gmail.com"
    assert "app-password-test" not in response.get_data(as_text=True)


def test_incomplete_configuration_blocks_delivery(app, client):
    create_admin(app)
    configure_email(app, password="")
    csrf = login(client)

    response = client.post(
        "/api/v1/admin/communications/test",
        json={"idempotency_key": "test-incomplete-configuration"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "email_not_configured"


def test_sandbox_redirects_delivery_and_records_audit(app, client, monkeypatch):
    create_admin(app)
    configure_email(app)
    csrf = login(client)
    sent = {}

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            sent.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def ehlo(self):
            sent["ehlo"] = sent.get("ehlo", 0) + 1

        def starttls(self, *, context):
            sent["tls"] = context is not None

        def login(self, username, password):
            sent.update(username=username, password=password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr("movimento7.services.email_delivery.smtplib.SMTP", FakeSmtp)
    payload = {
        "recipient": "artista@example.test",
        "idempotency_key": "test-sandbox-redirection",
    }

    response = client.post(
        "/api/v1/admin/communications/test",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    duplicate = client.post(
        "/api/v1/admin/communications/test",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.json["data"]["status"] == "sent"
    assert response.json["data"]["delivered_to"] == "mo**************@gmail.com"
    assert sent["host"] == "smtp.gmail.com"
    assert sent["port"] == 587
    assert sent["tls"] is True
    assert sent["username"] == "movimentosete777@gmail.com"
    assert sent["message"]["To"] == "movimentosete777@gmail.com"
    assert sent["message"]["Subject"].startswith("[SANDBOX]")
    assert duplicate.status_code == 200
    assert duplicate.json["data"]["duplicate"] is True
    with app.app_context():
        logs = db.session.scalars(select(CommunicationLog)).all()
        assert len(logs) == 1
        assert logs[0].status == "sent"
        assert logs[0].recipient_hash != "movimentosete777@gmail.com"


def test_log_mode_records_without_opening_smtp(app, client, monkeypatch):
    create_admin(app)
    configure_email(app, mode="log", password="")
    csrf = login(client)

    def unexpected_smtp(*args, **kwargs):
        raise AssertionError("SMTP não deve ser aberto no modo log")

    monkeypatch.setattr("movimento7.services.email_delivery.smtplib.SMTP", unexpected_smtp)
    response = client.post(
        "/api/v1/admin/communications/test",
        json={"idempotency_key": "test-log-only-delivery"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.json["data"]["status"] == "logged"
