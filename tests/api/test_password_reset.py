import re

from sqlalchemy import select
from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import (
    AdminPasswordReset,
    AdminUser,
    CommunicationLog,
    Permission,
    Role,
)
from movimento7.services.email_delivery import DeliveryResult


def create_admin(app):
    with app.app_context():
        permission = Permission(slug="dashboard.read", description="Dashboard")
        role = Role(slug="administrador", name="Administrador", permissions=[permission])
        user = AdminUser(
            email="admin@example.test",
            name="Admin Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add(user)
        db.session.commit()


def test_password_reset_is_non_enumerating_single_use_and_revokes_sessions(
    app, client, monkeypatch
):
    create_admin(app)
    active_login = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert active_login.status_code == 200
    recovery_client = app.test_client()
    delivered = {}

    def capture_delivery(*, recipient, subject, text_body):
        delivered.update(recipient=recipient, subject=subject, text_body=text_body)
        return DeliveryResult(status="sent", delivered_to=recipient)

    monkeypatch.setattr(
        "movimento7.services.communications.deliver_email", capture_delivery
    )
    unknown = recovery_client.post(
        "/api/v1/admin/auth/password-reset/request",
        json={"email": "missing@example.test"},
    )
    requested = recovery_client.post(
        "/api/v1/admin/auth/password-reset/request",
        json={"email": "admin@example.test"},
    )

    assert unknown.status_code == requested.status_code == 202
    assert unknown.json["data"] == requested.json["data"]
    assert delivered["recipient"] == "admin@example.test"
    assert "Redefinição de senha" in delivered["subject"]
    raw_token = re.search(r"token=([^\s]+)", delivered["text_body"]).group(1)

    changed = recovery_client.post(
        "/api/v1/admin/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "nova-senha-segura-teste",
            "password_confirmation": "nova-senha-segura-teste",
        },
    )
    reused = recovery_client.post(
        "/api/v1/admin/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "outra-senha-segura-teste",
            "password_confirmation": "outra-senha-segura-teste",
        },
    )

    assert changed.status_code == 200
    assert changed.json["data"]["changed"] is True
    assert reused.status_code == 422
    assert reused.json["error"]["code"] == "reset_token_invalid"
    assert client.get("/api/v1/admin/auth/session").status_code == 401
    assert recovery_client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    ).status_code == 401
    assert recovery_client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "nova-senha-segura-teste"},
    ).status_code == 200
    with app.app_context():
        reset = db.session.scalar(select(AdminPasswordReset))
        communication = db.session.scalar(select(CommunicationLog))
        assert reset.token_hash != raw_token
        assert reset.used_at is not None
        assert communication.template_key == "admin_password_reset"


def test_password_reset_rejects_weak_password_without_consuming_token(
    app, client, monkeypatch
):
    create_admin(app)
    delivered = {}

    def capture_delivery(*, recipient, subject, text_body):
        delivered["text_body"] = text_body
        return DeliveryResult(status="sent", delivered_to=recipient)

    monkeypatch.setattr(
        "movimento7.services.communications.deliver_email", capture_delivery
    )
    client.post(
        "/api/v1/admin/auth/password-reset/request",
        json={"email": "admin@example.test"},
    )
    raw_token = re.search(r"token=([^\s]+)", delivered["text_body"]).group(1)

    weak = client.post(
        "/api/v1/admin/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "curta",
            "password_confirmation": "diferente",
        },
    )

    assert weak.status_code == 422
    assert "new_password" in weak.json["error"]["fields"]
    assert "password_confirmation" in weak.json["error"]["fields"]
    with app.app_context():
        assert db.session.scalar(select(AdminPasswordReset)).used_at is None
