from uuid import UUID

from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import AdminUser, Partner, Permission, Role


def create_crud_admin(app):
    with app.app_context():
        permissions = [
            Permission(slug=slug, description=slug)
            for slug in ("partners.manage", "content.manage", "gallery.manage")
        ]
        role = Role(slug="crud-admin", name="CRUD Admin", permissions=permissions)
        admin = AdminUser(
            email="crud@example.test",
            name="CRUD Admin",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        db.session.add_all([admin, *permissions])
        db.session.commit()


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "crud@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def test_partner_crud_uses_soft_delete(app, client):
    create_crud_admin(app)
    csrf = login(client)
    created = client.post(
        "/api/v1/admin/partners",
        json={
            "name": "Parceiro CRUD",
            "slug": "parceiro-crud",
            "logo_path": "/logos/crud.svg",
        },
        headers={"X-CSRF-Token": csrf},
    )
    partner_id = created.json["data"]["id"]
    updated = client.patch(
        f"/api/v1/admin/partners/{partner_id}",
        json={"name": "Parceiro Atualizado", "active": False},
        headers={"X-CSRF-Token": csrf},
    )
    deleted = client.delete(
        f"/api/v1/admin/partners/{partner_id}",
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert deleted.status_code == 200
    with app.app_context():
        partner = db.session.get(Partner, UUID(partner_id))
        assert partner.deleted_at is not None
        assert partner.active is False


def test_content_archive_keeps_entry_and_archives_versions(app, client):
    create_crud_admin(app)
    csrf = login(client)
    published = client.post(
        "/api/v1/admin/content/home.hero/publish",
        json={"title": "Hero", "value": {"headline": "Olá"}},
        headers={"X-CSRF-Token": csrf},
    )
    archived = client.delete(
        "/api/v1/admin/content/home.hero",
        headers={"X-CSRF-Token": csrf},
    )
    listing = client.get("/api/v1/admin/content")

    assert published.status_code == 200
    assert archived.status_code == 200
    assert listing.status_code == 200
    assert listing.json["data"][0]["key"] == "home.hero"
