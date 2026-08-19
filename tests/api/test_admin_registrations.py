from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import (
    AdminUser,
    CommunicationLog,
    ParticipationCategory,
    Permission,
    Profile,
    Registration,
    RegistrationNote,
    RegistrationStatusHistory,
    Role,
)


def create_admin_and_registration(app, *, status="approved"):
    with app.app_context():
        permissions = [
            Permission(slug="registrations.read", description="Consultar inscrições"),
            Permission(slug="registrations.manage", description="Gerenciar inscrições"),
            Permission(slug="profiles.manage", description="Gerenciar perfis"),
        ]
        role = Role(slug="administrador", name="Administrador", permissions=permissions)
        admin = AdminUser(
            email="admin@example.test",
            name="Admin Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        category = ParticipationCategory(
            slug="mc",
            name="MC",
            active=True,
            accepts_file=True,
            accepts_link=True,
            extra_fields_json="[]",
        )
        db.session.add_all([admin, category])
        db.session.flush()
        registration = Registration(
            protocol="M7-ADMIN-001",
            upload_token_hash="a" * 64,
            category_id=category.id,
            full_name="Maria da Silva",
            professional_name="Maria MC",
            email="maria@example.test",
            phone_e164="+5511999999999",
            instagram_handle="mariamc",
            city="São Paulo",
            presentation="Artista independente com trabalho autoral.",
            portfolio_url="https://example.test/portfolio",
            extra_data_json='{"estilo": "rap"}',
            status=status,
            priority="normal",
            consent_at=datetime.now(UTC),
            privacy_version="2026-08",
            consent_purpose="inscrição e seleção",
        )
        db.session.add(registration)
        db.session.flush()
        db.session.add(
            RegistrationStatusHistory(
                registration_id=registration.id,
                old_status="reviewing",
                new_status=status,
                reason="Avaliação inicial",
                created_at=datetime.now(UTC),
            )
        )
        db.session.commit()
        return str(registration.id), str(admin.id)


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "admin@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def test_registration_detail_exposes_triage_context(app, client):
    registration_id, admin_id = create_admin_and_registration(app)
    login(client)

    response = client.get(f"/api/v1/admin/registrations/{registration_id}")

    assert response.status_code == 200
    data = response.json["data"]
    assert data["professional_name"] == "Maria MC"
    assert data["email"] == "maria@example.test"
    assert data["phone"] == "+5511999999999"
    assert data["category"]["name"] == "MC"
    assert data["extra_data"] == {"estilo": "rap"}
    assert data["history"][0]["reason"] == "Avaliação inicial"
    assert data["assignees"] == [
        {"id": admin_id, "name": "Admin Teste", "email": "admin@example.test"}
    ]


def test_triage_and_note_are_persisted_and_audited(app, client):
    registration_id, admin_id = create_admin_and_registration(app)
    csrf = login(client)

    triage = client.patch(
        f"/api/v1/admin/registrations/{registration_id}/triage",
        json={"priority": "urgent", "assigned_to_id": admin_id},
        headers={"X-CSRF-Token": csrf},
    )
    note = client.post(
        f"/api/v1/admin/registrations/{registration_id}/notes",
        json={"body": "Confirmar disponibilidade para a próxima edição.", "pinned": True},
        headers={"X-CSRF-Token": csrf},
    )

    assert triage.status_code == 200
    assert triage.json["data"]["priority"] == "urgent"
    assert triage.json["data"]["assigned_to"]["id"] == admin_id
    assert note.status_code == 201
    assert note.json["data"]["pinned"] is True
    with app.app_context():
        registration = db.session.get(Registration, UUID(registration_id))
        saved_note = db.session.scalar(select(RegistrationNote))
        assert registration.priority == "urgent"
        assert str(registration.assigned_to_id) == admin_id
        assert saved_note.body.startswith("Confirmar disponibilidade")


def test_approved_registration_creates_draft_profile(app, client):
    registration_id, _ = create_admin_and_registration(app, status="approved")
    csrf = login(client)

    response = client.post(
        f"/api/v1/admin/registrations/{registration_id}/profile",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201
    assert response.json["data"]["slug"] == "maria-mc"
    assert response.json["data"]["status"] == "draft"
    with app.app_context():
        profile = db.session.scalar(select(Profile))
        assert profile.display_name == "Maria MC"
        assert profile.bio.startswith("Artista independente")


def test_non_approved_registration_cannot_create_profile(app, client):
    registration_id, _ = create_admin_and_registration(app, status="reviewing")
    csrf = login(client)

    response = client.post(
        f"/api/v1/admin/registrations/{registration_id}/profile",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "invalid_state"


def test_status_change_records_approved_email(app, client):
    app.config.update(
        EMAIL_DELIVERY_MODE="log",
        EMAIL_FROM_ADDRESS="noreply@example.test",
    )
    registration_id, _ = create_admin_and_registration(app, status="reviewing")
    csrf = login(client)

    response = client.patch(
        f"/api/v1/admin/registrations/{registration_id}/status",
        json={"status": "approved", "reason": "Selecionada pela curadoria"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json["data"]["notification_status"] == "logged"
    with app.app_context():
        communication = db.session.scalar(select(CommunicationLog))
        assert communication.template_key == "registration_status_approved"
        assert communication.status == "logged"
        assert communication.registration_id == UUID(registration_id)
