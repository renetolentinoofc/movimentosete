from datetime import UTC, datetime, timedelta

from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import AdminUser, EventEdition, Permission, Role


def create_admin(app):
    with app.app_context():
        permission = Permission(slug="events.manage", description="Administrar edições")
        role = Role(slug="producao", name="Produção", permissions=[permission])
        admin = AdminUser(
            email="producao@example.test",
            name="Produção Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add(admin)
        db.session.commit()


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "producao@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def edition_payload(*, name="Edição Teste", slug="edicao-teste", offset_days=0):
    now = datetime.now(UTC) + timedelta(days=offset_days)
    return {
        "name": name,
        "slug": slug,
        "description": "Programação de teste da edição.",
        "starts_at": (now + timedelta(days=20)).isoformat(),
        "ends_at": (now + timedelta(days=21)).isoformat(),
        "registration_opens_at": (now - timedelta(days=1)).isoformat(),
        "registration_closes_at": (now + timedelta(days=10)).isoformat(),
        "location": "Centro Cultural",
        "address": "Rua de Teste, 7",
        "map_url": "https://example.test/mapa",
        "capacity": 100,
        "retention_days": 730,
    }


def test_create_update_publish_and_close_edition(app, client):
    create_admin(app)
    csrf = login(client)

    created = client.post(
        "/api/v1/admin/editions",
        json=edition_payload(),
        headers={"X-CSRF-Token": csrf},
    )
    edition_id = created.json["data"]["id"]
    updated_payload = edition_payload(name="Edição Atualizada")
    updated_payload["capacity"] = 120
    updated = client.patch(
        f"/api/v1/admin/editions/{edition_id}",
        json=updated_payload,
        headers={"X-CSRF-Token": csrf},
    )
    published = client.patch(
        f"/api/v1/admin/editions/{edition_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )
    listing = client.get("/api/v1/admin/editions")
    closed = client.patch(
        f"/api/v1/admin/editions/{edition_id}/status",
        json={"status": "closed"},
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert created.json["data"]["status"] == "draft"
    assert updated.status_code == 200
    assert updated.json["data"]["name"] == "Edição Atualizada"
    assert updated.json["data"]["capacity"] == 120
    assert published.status_code == 200
    assert published.json["data"]["registration_open"] is True
    assert published.json["data"]["published_at"] is not None
    assert listing.json["data"][0]["registration_count"] == 0
    assert closed.status_code == 200
    assert closed.json["data"]["status"] == "closed"
    assert closed.json["data"]["registration_open"] is False


def test_published_registration_windows_cannot_overlap(app, client):
    create_admin(app)
    csrf = login(client)
    first = client.post(
        "/api/v1/admin/editions",
        json=edition_payload(name="Primeira", slug="primeira"),
        headers={"X-CSRF-Token": csrf},
    )
    second = client.post(
        "/api/v1/admin/editions",
        json=edition_payload(name="Segunda", slug="segunda"),
        headers={"X-CSRF-Token": csrf},
    )
    client.patch(
        f"/api/v1/admin/editions/{first.json['data']['id']}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )

    conflict = client.patch(
        f"/api/v1/admin/editions/{second.json['data']['id']}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )

    assert conflict.status_code == 422
    assert conflict.json["error"]["code"] == "edition_incomplete"
    assert "registration_opens_at" in conflict.json["error"]["fields"]


def test_invalid_schedule_is_rejected(app, client):
    create_admin(app)
    csrf = login(client)
    payload = edition_payload()
    payload["registration_closes_at"] = payload["ends_at"]

    response = client.post(
        "/api/v1/admin/editions",
        json=payload,
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert "registration_closes_at" in response.json["error"]["fields"]
    with app.app_context():
        assert db.session.scalar(db.select(EventEdition)) is None
