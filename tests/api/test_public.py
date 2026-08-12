from datetime import UTC, datetime, timedelta

from movimento7.extensions import db
from movimento7.models import EventEdition, ParticipationCategory, Registration


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
        assert registration.phone_e164 == "+5571999990000"
        assert registration.instagram_handle == "arte.teste"


def test_registration_requires_open_edition(app, client):
    with app.app_context():
        db.session.add(ParticipationCategory(name="MC", slug="mc"))
        db.session.commit()
    response = client.post(
        "/api/v1/registrations",
        json={
            "full_name": "Pessoa Teste",
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
    response = client.post("/api/v1/contact", json={"website": "spam.example"})
    assert response.status_code == 201
