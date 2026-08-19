import io
from uuid import UUID

from PIL import Image
from sqlalchemy import select
from werkzeug.security import generate_password_hash

from movimento7.extensions import db
from movimento7.models import (
    AdminUser,
    ParticipationCategory,
    Permission,
    PortfolioAsset,
    Profile,
    ProfileCategory,
    Role,
)


def create_profile_context(app):
    with app.app_context():
        permission = Permission(slug="profiles.manage", description="Gerenciar perfis")
        role = Role(slug="editor", name="Editor", permissions=[permission])
        admin = AdminUser(
            email="editor@example.test",
            name="Editora Teste",
            password_hash=generate_password_hash("senha-segura-teste"),
            roles=[role],
        )
        mc = ParticipationCategory(
            slug="mc",
            name="MC",
            active=True,
            accepts_file=True,
            accepts_link=True,
            extra_fields_json="[]",
            display_order=1,
        )
        dj = ParticipationCategory(
            slug="dj",
            name="DJ",
            active=True,
            accepts_file=True,
            accepts_link=True,
            extra_fields_json="[]",
            display_order=2,
        )
        db.session.add_all([admin, mc, dj])
        db.session.flush()
        profile = Profile(
            slug="maria-mc",
            display_name="Maria MC",
            bio="Artista independente com trabalho autoral.",
            city="São Paulo",
            instagram_handle="mariamc",
            status="draft",
        )
        db.session.add(profile)
        db.session.flush()
        db.session.add(ProfileCategory(profile_id=profile.id, category_id=mc.id))
        asset = PortfolioAsset(
            profile_id=profile.id,
            provider="local",
            storage_key="portfolio.jpg",
            media_type="image",
            alt_text="Maria MC durante apresentação",
            display_order=0,
            active=True,
        )
        db.session.add(asset)
        db.session.commit()
        return str(profile.id), str(asset.id), str(mc.id), str(dj.id)


def login(client):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": "editor@example.test", "password": "senha-segura-teste"},
    )
    assert response.status_code == 200
    return response.json["data"]["csrf_token"]


def test_profile_list_and_detail(app, client):
    profile_id, asset_id, mc_id, _ = create_profile_context(app)
    login(client)

    listing = client.get("/api/v1/admin/profiles?status=draft&q=Maria")
    detail = client.get(f"/api/v1/admin/profiles/{profile_id}")

    assert listing.status_code == 200
    assert listing.json["data"][0]["display_name"] == "Maria MC"
    assert listing.json["data"][0]["asset_count"] == 1
    assert detail.status_code == 200
    assert detail.json["data"]["category_ids"] == [mc_id]
    assert detail.json["data"]["assets"][0]["id"] == asset_id
    assert len(detail.json["data"]["available_categories"]) == 2


def test_profile_update_replaces_categories(app, client):
    profile_id, _, _, dj_id = create_profile_context(app)
    csrf = login(client)

    response = client.patch(
        f"/api/v1/admin/profiles/{profile_id}",
        json={
            "display_name": "Maria MC Atualizada",
            "slug": "maria-mc-atualizada",
            "bio": "Biografia atualizada e pronta para publicação.",
            "city": "Guarulhos",
            "instagram": "maria.atualizada",
            "featured": True,
            "category_ids": [dj_id],
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    with app.app_context():
        profile = db.session.get(Profile, UUID(profile_id))
        categories = db.session.scalars(
            select(ProfileCategory).where(ProfileCategory.profile_id == profile.id)
        ).all()
        assert profile.display_name == "Maria MC Atualizada"
        assert profile.slug == "maria-mc-atualizada"
        assert profile.featured is True
        assert [str(item.category_id) for item in categories] == [dj_id]


def test_profile_publish_and_unpublish(app, client):
    profile_id, _, _, _ = create_profile_context(app)
    csrf = login(client)

    published = client.patch(
        f"/api/v1/admin/profiles/{profile_id}/status",
        json={"status": "published"},
        headers={"X-CSRF-Token": csrf},
    )
    draft = client.patch(
        f"/api/v1/admin/profiles/{profile_id}/status",
        json={"status": "draft"},
        headers={"X-CSRF-Token": csrf},
    )

    assert published.status_code == 200
    assert published.json["data"]["status"] == "published"
    assert published.json["data"]["published_at"]
    assert draft.status_code == 200
    assert draft.json["data"]["status"] == "draft"


def test_profile_asset_metadata_update(app, client):
    _, asset_id, _, _ = create_profile_context(app)
    csrf = login(client)

    response = client.patch(
        f"/api/v1/admin/profile-assets/{asset_id}",
        json={
            "alt_text": "Retrato de Maria MC no palco",
            "credit": "Foto: Movimento 7",
            "display_order": 3,
            "active": False,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json["data"] == {
        "id": asset_id,
        "alt_text": "Retrato de Maria MC no palco",
        "credit": "Foto: Movimento 7",
        "display_order": 3,
        "active": False,
    }


def portfolio_upload(size=(2400, 1200)):
    content = io.BytesIO()
    Image.new("RGB", size, (12, 104, 94)).save(content, format="PNG")
    content.seek(0)
    return content


def test_profile_asset_upload_processes_and_stores_webp(app, client, tmp_path, monkeypatch):
    profile_id, _, _, _ = create_profile_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)

    response = client.post(
        f"/api/v1/admin/profiles/{profile_id}/assets",
        data={
            "file": (portfolio_upload(), "retrato-grande.png"),
            "alt_text": "Maria MC em retrato de divulgação",
            "credit": "Foto: Movimento 7",
        },
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    assert response.json["data"]["width"] == 1920
    assert response.json["data"]["height"] == 960
    with app.app_context():
        asset = db.session.get(PortfolioAsset, UUID(response.json["data"]["id"]))
        stored = tmp_path / "instance" / "uploads" / "registrations" / asset.storage_key
        assert asset.storage_key.endswith(".webp")
        assert stored.is_file()
        with Image.open(stored) as image:
            assert image.format == "WEBP"
            assert image.size == (1920, 960)


def test_profile_assets_reorder_cover_and_delete(app, client, tmp_path, monkeypatch):
    profile_id, original_id, _, _ = create_profile_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)
    uploaded = client.post(
        f"/api/v1/admin/profiles/{profile_id}/assets",
        data={"file": (portfolio_upload((400, 400)), "nova.png")},
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )
    uploaded_id = uploaded.json["data"]["id"]

    reordered = client.patch(
        f"/api/v1/admin/profiles/{profile_id}/assets/order",
        json={"asset_ids": [uploaded_id, original_id]},
        headers={"X-CSRF-Token": csrf},
    )
    cover = client.post(
        f"/api/v1/admin/profile-assets/{original_id}/cover",
        headers={"X-CSRF-Token": csrf},
    )
    with app.app_context():
        uploaded_asset = db.session.get(PortfolioAsset, UUID(uploaded_id))
        stored = (
            tmp_path
            / "instance"
            / "uploads"
            / "registrations"
            / uploaded_asset.storage_key
        )
        assert stored.is_file()

    removed = client.delete(
        f"/api/v1/admin/profile-assets/{uploaded_id}",
        headers={"X-CSRF-Token": csrf},
    )

    assert reordered.status_code == 200
    assert reordered.json["data"]["asset_ids"] == [uploaded_id, original_id]
    assert cover.status_code == 200
    assert cover.json["data"]["display_order"] == 0
    assert removed.status_code == 200
    assert removed.json["data"]["deleted"] is True
    assert not stored.exists()
    with app.app_context():
        original = db.session.get(PortfolioAsset, UUID(original_id))
        assert original.display_order == 0


def test_profile_asset_upload_rejects_invalid_image(app, client, tmp_path, monkeypatch):
    profile_id, _, _, _ = create_profile_context(app)
    csrf = login(client)
    monkeypatch.chdir(tmp_path)

    response = client.post(
        f"/api/v1/admin/profiles/{profile_id}/assets",
        data={
            "file": (io.BytesIO(b"not-an-image"), "arquivo.png"),
            "alt_text": "Arquivo inválido para teste",
        },
        headers={"X-CSRF-Token": csrf},
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    assert response.json["error"]["code"] == "validation_error"
    assert not (tmp_path / "instance").exists()
