from types import SimpleNamespace

from movimento7.services.shipping import quote_shipping


def test_melhor_envio_quote_uses_custom_price_and_delivery(monkeypatch, app):
    app.config.update(
        SHIPPING_PROVIDER="melhor_envio",
        MELHOR_ENVIO_ACCESS_TOKEN="token",
        MELHOR_ENVIO_API_BASE_URL="https://shipping.test/api/v2/me",
        MELHOR_ENVIO_USER_AGENT="Movimento 7 suporte@test.local",
        SHIPPING_ORIGIN_POSTAL_CODE="01001000",
    )
    response = SimpleNamespace(
        json=lambda: [
            {
                "id": 1,
                "name": "PAC",
                "price": "29.90",
                "custom_price": "24.90",
                "delivery_time": 8,
                "custom_delivery_time": 6,
            }
        ],
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr("movimento7.services.shipping.requests.post", lambda *args, **kwargs: response)

    with app.app_context():
        quote = quote_shipping(
            subtotal_cents=10000,
            postal_code="01310-100",
            state="sp",
            products=[{"id": "variant-1", "quantity": 1}],
        )

    assert quote.shipping_cents == 2490
    assert quote.estimated_days == 6
    assert quote.provider_reference == "1"


def test_pickup_is_free_when_enabled(app):
    app.config.update(SHIPPING_PICKUP_ENABLED=True, SHIPPING_PICKUP_LABEL="Ateliê")

    with app.app_context():
        quote = quote_shipping(
            subtotal_cents=1000,
            postal_code="01310-100",
            state="SP",
            fulfillment_method="pickup",
        )

    assert quote.method == "pickup"
    assert quote.shipping_cents == 0
    assert quote.label == "Ateliê"
