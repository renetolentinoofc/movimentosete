from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import (
    AdminUser,
    AuditLog,
    CommunicationLog,
    ContactMessage,
    ContactNote,
    ContactReply,
    ContactStatusHistory,
    Permission,
    Role,
)


def create_admin_and_contact(app, *, status="received"):
    with app.app_context():
        permissions = [
            Permission(slug="contacts.read", description="Consultar contatos"),
            Permission(slug="contacts.manage", description="Administrar contatos"),
        ]
        role = Role(slug="atendimento", name="Atendimento", permissions=permissions)
        admin = AdminUser(
            email="admin@example.test",
            name="Atendimento Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        contact = ContactMessage(
            protocol="CT-ADMIN-001",
            name="Joana da Silva",
            email="joana@example.test",
            phone_e164="+5511999999999",
            subject="Parceria cultural",
            message="Gostaria de conversar sobre uma parceria para a próxima edição.",
            status=status,
            consent_at=datetime.now(UTC),
            privacy_version="2026-08",
        )
        db.session.add_all([admin, contact])
        db.session.commit()
        return str(contact.id), str(admin.id)


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def configure_log_email(app):
    app.config.update(
        EMAIL_DELIVERY_MODE="log",
        EMAIL_FROM_ADDRESS="contato@example.test",
        EMAIL_REPLY_TO="contato@example.test",
    )


def test_contacts_list_and_detail_expose_operational_context(app, client):
    contact_id, admin_id = create_admin_and_contact(app)
    login(client)

    listing = client.get("/api/v1/admin/contacts?q=Joana&status=received")
    detail = client.get(f"/api/v1/admin/contacts/{contact_id}")

    assert listing.status_code == 200
    assert listing.json["data"][0]["protocol"] == "CT-ADMIN-001"
    assert listing.json["meta"]["has_more"] is False
    assert detail.status_code == 200
    data = detail.json["data"]
    assert data["email"] == "joana@example.test"
    assert data["subject"] == "Parceria cultural"
    assert data["notes"] == []
    assert data["history"] == []
    assert data["replies"] == []
    assert data["assignees"] == [
        {"id": admin_id, "name": "Atendimento Teste", "email": "admin@example.test"}
    ]


def test_triage_and_internal_note_are_persisted_and_audited(app, client):
    contact_id, admin_id = create_admin_and_contact(app)
    csrf = login(client)

    triage = client.patch(
        f"/api/v1/admin/contacts/{contact_id}/triage",
        json={
            "status": "in_progress",
            "assigned_to_id": admin_id,
            "reason": "Atendimento iniciado",
        },
        headers={"X-CSRF-Token": csrf},
    )
    note = client.post(
        f"/api/v1/admin/contacts/{contact_id}/notes",
        json={"body": "Retornar com a proposta institucional até sexta-feira."},
        headers={"X-CSRF-Token": csrf},
    )

    assert triage.status_code == 200
    assert triage.json["data"]["status"] == "in_progress"
    assert triage.json["data"]["assigned_to"]["id"] == admin_id
    assert note.status_code == 201
    with app.app_context():
        contact = db.session.get(ContactMessage, UUID(contact_id))
        saved_note = db.session.scalar(select(ContactNote))
        history = db.session.scalar(select(ContactStatusHistory))
        actions = set(db.session.scalars(select(AuditLog.action)).all())
        assert str(contact.assigned_to_id) == admin_id
        assert saved_note.body.startswith("Retornar")
        assert history.old_status == "received"
        assert history.new_status == "in_progress"
        assert {"contact.triage_changed", "contact.note_created"} <= actions


def test_reply_is_idempotent_linked_and_starts_service(app, client):
    configure_log_email(app)
    contact_id, _ = create_admin_and_contact(app)
    csrf = login(client)
    payload = {
        "subject": "Re: Parceria cultural — CT-ADMIN-001",
        "message": "Olá! Podemos agendar uma conversa na próxima semana.",
        "idempotency_key": "contact-reply-admin-test-001",
    }

    response = client.post(
        f"/api/v1/admin/contacts/{contact_id}/reply",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )
    duplicate = client.post(
        f"/api/v1/admin/contacts/{contact_id}/reply",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.json["data"]["delivery_status"] == "logged"
    assert response.json["data"]["contact_status"] == "in_progress"
    assert duplicate.status_code == 200
    assert duplicate.json["data"]["duplicate"] is True
    with app.app_context():
        contact = db.session.get(ContactMessage, UUID(contact_id))
        communication = db.session.scalar(select(CommunicationLog))
        reply = db.session.scalar(select(ContactReply))
        assert contact.status == "in_progress"
        assert communication.contact_id == UUID(contact_id)
        assert communication.template_key == "contact_reply"
        assert reply.communication_log_id == communication.id
        assert reply.body.startswith("Olá!")
        assert db.session.scalar(select(func.count()).select_from(ContactReply)) == 1


def test_reply_requires_email_configuration(app, client):
    contact_id, _ = create_admin_and_contact(app)
    csrf = login(client)

    response = client.post(
        f"/api/v1/admin/contacts/{contact_id}/reply",
        json={
            "subject": "Re: Parceria cultural",
            "message": "Vamos conversar.",
            "idempotency_key": "contact-email-not-configured",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "email_not_configured"
