from uuid import UUID

from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import (
    AdminUser,
    Permission,
    PrivacyRequest,
    Role,
)


def create_admin(app):
    with app.app_context():
        permissions = [
            Permission(slug=slug, description=slug)
            for slug in ("auction.manage", "users.manage", "privacy.manage")
        ]
        role = Role(slug="administrator", name="Administrator", permissions=permissions)
        admin = AdminUser(
            email="step-six@example.test",
            name="Administrador de Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add_all([admin, *permissions])
        db.session.commit()


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "step-six@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def test_auction_lot_lifecycle(app, client):
    create_admin(app)
    csrf = login(client)
    created = client.post(
        "/api/v1/admin/auction-lots",
        json={
            "title": "Obra de teste",
            "slug": "obra-de-teste",
            "artist_name": "Artista de Teste",
            "starting_bid_cents": 10000,
            "minimum_increment_cents": 500,
        },
        headers={"X-CSRF-Token": csrf},
    )
    lot_id = created.json["data"]["id"]
    listing = client.get("/api/v1/admin/auction-lots")
    published = client.patch(
        f"/api/v1/admin/auction-lots/{lot_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )
    updated = client.patch(
        f"/api/v1/admin/auction-lots/{lot_id}",
        json={"title": "Obra revisada", "starting_bid_cents": 12000},
        headers={"X-CSRF-Token": csrf},
    )
    archived = client.delete(
        f"/api/v1/admin/auction-lots/{lot_id}",
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert listing.status_code == 200
    assert listing.json["data"][0]["artist_name"] == "Artista de Teste"
    assert published.status_code == 200
    assert published.json["data"]["status"] == "published"
    assert updated.status_code == 200
    assert archived.status_code == 200
    assert archived.json["data"]["status"] == "archived"


def test_user_creation_assigns_role(app, client):
    create_admin(app)
    csrf = login(client)
    with app.app_context():
        db.session.add(Role(slug="editor", name="Editor"))
        db.session.commit()
    created = client.post(
        "/api/v1/admin/users",
        json={
            "name": "Editora Nova",
            "email": "editora@example.test",
            "password": "senha-nova-segura",
            "roles": ["editor"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    listing = client.get("/api/v1/admin/users")

    assert created.status_code == 201
    assert listing.status_code == 200
    assert listing.json["data"][-1]["email"] == "editora@example.test"
    assert listing.json["data"][-1]["must_change_password"] is True
    user_id = created.json["data"]["id"]
    updated = client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"name": "Editora Atualizada", "active": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json["data"]["active"] is False


def test_privacy_request_status_is_audited(app, client):
    create_admin(app)
    csrf = login(client)
    with app.app_context():
        request = PrivacyRequest(
            protocol="LGPD-202608-TEST",
            request_type="access",
            subject_reference_hash="a" * 64,
        )
        db.session.add(request)
        db.session.commit()
        request_id = str(request.id)
    listing = client.get("/api/v1/admin/privacy/requests")
    resolved = client.patch(
        f"/api/v1/admin/privacy/requests/{request_id}/status",
        json={"status": "resolved"},
        headers={"X-CSRF-Token": csrf},
    )

    assert listing.status_code == 200
    assert listing.json["data"][0]["protocol"] == "LGPD-202608-TEST"
    assert resolved.status_code == 200
    assert resolved.json["data"]["status"] == "resolved"
    with app.app_context():
        assert db.session.get(PrivacyRequest, UUID(request_id)).resolved_by_id is not None
