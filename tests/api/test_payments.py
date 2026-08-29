import hashlib
import hmac
import json

import pytest
from movimento7.services.payments import (
    ManualPaymentProvider,
    PaymentRequest,
    get_payment_provider,
)


def test_manual_provider_never_approves_a_payment():
    result = ManualPaymentProvider().create(
        PaymentRequest(
            order_code="PED-TEST",
            amount_cents=1500,
            currency="BRL",
            idempotency_key="checkout-key",
        )
    )

    assert result.status == "pending_manual"
    assert result.provider_reference is None
    assert result.instructions


def test_payment_provider_factory_resolves_manual(app):
    with app.app_context():
        assert isinstance(get_payment_provider(), ManualPaymentProvider)


def test_payment_provider_factory_rejects_unimplemented_provider(app):
    app.config["PAYMENT_PROVIDER"] = "stripe"

    with app.app_context(), pytest.raises(RuntimeError, match="não implementado"):
        get_payment_provider()


def test_mercadopago_webhook_signature_is_verified(app):
    from movimento7.services.payments import MercadoPagoProvider

    app.config["PAYMENT_WEBHOOK_SECRET"] = "webhook-secret"
    app.config["MERCADOPAGO_ACCESS_TOKEN"] = "access-token"
    body = json.dumps({"data": {"id": "123"}}).encode()
    request_id = "request-123"
    timestamp = "1704908010"
    manifest = f"id:123;request-id:{request_id};ts:{timestamp};"
    digest = hmac.new(b"webhook-secret", manifest.encode(), hashlib.sha256).hexdigest()

    with app.test_request_context(
        "/api/v1/payments/webhook/mercadopago?data.id=123",
        method="POST",
        data=body,
        headers={"x-request-id": request_id, "x-signature": f"ts={timestamp},v1={digest}"},
    ):
        assert MercadoPagoProvider().verify_webhook(body, f"ts={timestamp},v1={digest}")


def test_mercadopago_auction_authorization_uses_manual_capture(app, monkeypatch):
    from movimento7.services.payments import MercadoPagoProvider

    app.config["MERCADOPAGO_ACCESS_TOKEN"] = "access-token"
    captured = {}

    def fake_request(method, path, **kwargs):
        captured.update(method=method, path=path, kwargs=kwargs)
        return {
            "id": "order-123",
            "transactions": {"payments": [{"id": "payment-123", "status_detail": "waiting_capture"}]},
        }

    with app.app_context():
        provider = MercadoPagoProvider()
        monkeypatch.setattr(provider, "_request", fake_request)
        result = provider.authorize_auction(
            external_reference="auction:lot:key",
            amount_cents=12500,
            payer_email="buyer@example.com",
            card_token="card-token",
            payment_method_id="master",
            installments=1,
            idempotency_key="auction-key-123",
        )

    assert result.status == "authorized"
    assert result.provider_reference == "order-123"
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/orders"
    assert captured["kwargs"]["json"]["capture_mode"] == "manual"
