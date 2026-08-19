from datetime import UTC, datetime, timedelta

from movimento7.extensions import db
from movimento7.models import (
    CommunicationLog,
    ContactMessage,
    EventEdition,
    ParticipationCategory,
    PortfolioAsset,
    Profile,
    ProfileCategory,
    Registration,
)


def test_health_is_safe(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json["data"]["status"] == "ok"
    assert "DATABASE" not in response.text


def test_categories_empty_envelope(client):
    response = client.get("/api/v1/categories")
    assert response.status_code == 200
    assert response.json["data"] == []
    assert response.json["error"] is None


def test_registration_persists_protocol(app, client):
    app.config.update(
        EMAIL_DELIVERY_MODE="log",
        EMAIL_FROM_ADDRESS="noreply@example.test",
    )
    with app.app_context():
        now = datetime.now(UTC)
        category = ParticipationCategory(name="Artista", slug="artista")
        edition = EventEdition(
            name="Edição de teste",
            slug="edicao-teste",
            status="published",
            registration_opens_at=now - timedelta(days=1),
            registration_closes_at=now + timedelta(days=1),
        )
        db.session.add_all([category, edition])
        db.session.commit()
    response = client.post(
        "/api/v1/registrations",
        json={
            "full_name": "Pessoa Teste",
            "professional_name": "Arte Teste",
            "email": "pessoa@example.test",
            "phone": "(71) 99999-0000",
            "instagram": "@arte.teste",
            "city": "Salvador",
            "category": "artista",
            "presentation": "Uma apresentação válida sem dados pessoais reais.",
            "portfolio_url": "https://example.test/portfolio",
            "privacy_accepted": True,
            "privacy_version": "test-v1",
        },
    )
    assert response.status_code == 201
    assert response.json["data"]["protocol"].startswith("M7-")
    assert response.json["data"]["upload_token"]
    with app.app_context():
        registration = db.session.scalar(db.select(Registration))
        assert registration is not None
        assert registration.email == "pessoa@example.test"
        assert registration.phone_e164 == "+5571999990000"
        assert registration.instagram_handle == "arte.teste"
        communication = db.session.scalar(db.select(CommunicationLog))
        assert communication.template_key == "registration_received"
        assert communication.status == "logged"


def test_registration_requires_open_edition(app, client):
    with app.app_context():
        db.session.add(ParticipationCategory(name="MC", slug="mc"))
        db.session.commit()
    response = client.post(
        "/api/v1/registrations",
        json={
            "full_name": "Pessoa Teste",
            "email": "pessoa@example.test",
            "phone": "71999990000",
            "city": "Salvador",
            "category": "mc",
            "presentation": "Uma apresentação suficientemente completa.",
            "privacy_accepted": True,
            "privacy_version": "test-v1",
        },
    )
    assert response.status_code == 422
    assert "edition" in response.json["error"]["fields"]


def test_contact_honeypot_does_not_persist(app, client):
    response = client.post(
        "/api/v1/contact", json={"fax_number_for_bots": "spam.example"}
    )
    assert response.status_code == 201
    with app.app_context():
        assert db.session.scalar(db.select(ContactMessage)) is None


def test_contact_is_persisted_and_forwarded(app, client):
    app.config.update(
        EMAIL_DELIVERY_MODE="log",
        EMAIL_FROM_ADDRESS="noreply@example.test",
        EMAIL_CONTACT_RECIPIENT="contato@example.test",
    )

    response = client.post(
        "/api/v1/contact",
        json={
            "name": "Pessoa Contato",
            "email": "pessoa@example.test",
            "subject": "Parceria",
            "message": "Gostaria de conversar sobre uma parceria cultural.",
            "privacy_accepted": True,
            "privacy_version": "test-v1",
        },
    )

    assert response.status_code == 201
    assert response.json["data"]["notification_status"] == "logged"
    with app.app_context():
        contact = db.session.scalar(db.select(ContactMessage))
        communication = db.session.scalar(db.select(CommunicationLog))
        assert contact.email == "pessoa@example.test"
        assert communication.template_key == "contact_message_received"
        assert communication.status == "logged"


def create_public_profile(app, *, status="published"):
    with app.app_context():
        category = db.session.scalar(
            db.select(ParticipationCategory).where(ParticipationCategory.slug == "musica")
        )
        if not category:
            category = ParticipationCategory(
                name="Música",
                slug="musica",
                active=True,
                display_order=1,
            )
        profile = Profile(
            slug=f"luna-{status}",
            display_name="Luna MC",
            bio="Artista independente que transforma vivências em música.",
            city="Salvador",
            instagram_handle="lunamc",
            status=status,
            featured=True,
            published_at=datetime.now(UTC) if status == "published" else None,
        )
        db.session.add_all([category, profile])
        db.session.flush()
        asset = PortfolioAsset(
            profile_id=profile.id,
            provider="local",
            storage_key="luna.jpg",
            media_type="image",
            alt_text="Luna MC cantando no palco",
            credit="Movimento 7",
            display_order=0,
            active=True,
        )
        db.session.add_all(
            [ProfileCategory(profile_id=profile.id, category_id=category.id), asset]
        )
        db.session.commit()
        return profile.slug, str(asset.id)


def test_public_profiles_support_filters_and_cover(app, client):
    slug, asset_id = create_public_profile(app)

    response = client.get("/api/v1/profiles?q=Luna&city=Salvador&category=musica")
    empty = client.get("/api/v1/profiles?category=danca")

    assert response.status_code == 200
    assert response.json["data"] == [
        {
            "slug": slug,
            "display_name": "Luna MC",
            "bio": "Artista independente que transforma vivências em música.",
            "city": "Salvador",
            "instagram": "lunamc",
            "featured": True,
            "categories": ["Música"],
            "category_slugs": ["musica"],
            "cover": {
                "url": f"/api/v1/profile-assets/{asset_id}/file",
                "type": "image",
                "alt": "Luna MC cantando no palco",
                "credit": "Movimento 7",
            },
        }
    ]
    assert empty.json["data"] == []


def test_public_profile_detail_hides_drafts(app, client):
    published_slug, asset_id = create_public_profile(app)
    draft_slug, _ = create_public_profile(app, status="draft")

    detail = client.get(f"/api/v1/profiles/{published_slug}")
    hidden = client.get(f"/api/v1/profiles/{draft_slug}")

    assert detail.status_code == 200
    assert detail.json["data"]["categories"] == ["Música"]
    assert detail.json["data"]["portfolio"][0]["id"] == asset_id
    assert hidden.status_code == 404


def test_public_profile_asset_only_serves_published_media(app, client, tmp_path, monkeypatch):
    _, published_asset_id = create_public_profile(app)
    _, draft_asset_id = create_public_profile(app, status="draft")
    media_root = tmp_path / "instance" / "uploads" / "registrations"
    media_root.mkdir(parents=True)
    (media_root / "luna.jpg").write_bytes(b"public-image-test")
    monkeypatch.chdir(tmp_path)

    visible = client.get(f"/api/v1/profile-assets/{published_asset_id}/file")
    hidden = client.get(f"/api/v1/profile-assets/{draft_asset_id}/file")

    assert visible.status_code == 200
    assert visible.data == b"public-image-test"
    assert hidden.status_code == 404
