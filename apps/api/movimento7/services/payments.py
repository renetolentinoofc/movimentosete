import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from flask import current_app, request
from sqlalchemy import select

from ..extensions import db
from ..models import (
    InventoryMovement,
    InventoryReservation,
    Order,
    OrderStatusHistory,
    Payment,
    ProductVariant,
)


@dataclass(frozen=True)
class PaymentRequest:
    order_code: str
    amount_cents: int
    currency: str
    idempotency_key: str
    customer_email: str | None = None
    notification_url: str | None = None


@dataclass(frozen=True)
class PaymentResult:
    status: str
    provider_reference: str | None = None
    instructions: str | None = None
    checkout_url: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class PaymentWebhook:
    provider_reference: str
    status: str
    failure_code: str | None = None
    order_code: str | None = None
    amount_cents: int | None = None


class PaymentProvider(ABC):
    @abstractmethod
    def create(self, request: PaymentRequest) -> PaymentResult:
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, body: bytes, signature: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(self, body: bytes) -> PaymentWebhook | None:
        raise NotImplementedError

    @abstractmethod
    def refund(self, provider_reference: str, amount_cents: int | None = None) -> PaymentResult:
        raise NotImplementedError

    @abstractmethod
    def reconcile(self, provider_reference: str) -> PaymentResult | None:
        raise NotImplementedError


class ManualPaymentProvider(PaymentProvider):
    """Modo honesto: registra pedido pendente, sem declarar pagamento aprovado."""

    def create(self, request: PaymentRequest) -> PaymentResult:
        return PaymentResult(
            status="pending_manual",
            instructions="A equipe confirmará disponibilidade e instruções de pagamento.",
        )

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return False

    def parse_webhook(self, body: bytes) -> PaymentWebhook | None:
        return None

    def refund(self, provider_reference: str, amount_cents: int | None = None) -> PaymentResult:
        return PaymentResult(status="unsupported", instructions="Estorno manual necessário.")

    def reconcile(self, provider_reference: str) -> PaymentResult | None:
        return None


def get_payment_provider() -> PaymentProvider:
    """Resolve o gateway configurado sem permitir fallback silencioso inseguro."""
    provider = str(current_app.config.get("PAYMENT_PROVIDER", "manual")).strip().lower()
    if provider == "manual":
        return ManualPaymentProvider()
    if provider == "mercadopago":
        return MercadoPagoProvider()
    raise RuntimeError(
        f"Provedor de pagamentos não implementado: {provider}. "
        "Configure PAYMENT_PROVIDER=manual ou instale um adaptador homologado."
    )


class MercadoPagoError(RuntimeError):
    pass


class MercadoPagoProvider(PaymentProvider):
    """Adaptador Checkout Pro do Mercado Pago, usando somente a API oficial."""

    def __init__(self) -> None:
        self.base_url = str(
            current_app.config.get("MERCADOPAGO_API_BASE_URL", "https://api.mercadopago.com")
        ).rstrip("/")
        self.access_token = str(current_app.config.get("MERCADOPAGO_ACCESS_TOKEN", "")).strip()
        if not self.access_token:
            raise MercadoPagoError("MERCADOPAGO_ACCESS_TOKEN não configurado")

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.access_token}", **kwargs.pop("headers", {})}
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=10,
                **kwargs,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise MercadoPagoError("Falha na comunicação com o Mercado Pago") from error
        if not isinstance(data, dict):
            raise MercadoPagoError("Resposta inválida do Mercado Pago")
        return data

    def create(self, request_data: PaymentRequest) -> PaymentResult:
        public_url = current_app.config["PUBLIC_BASE_URL"]
        preference = self._request(
            "POST",
            "/checkout/preferences",
            headers={"X-Idempotency-Key": request_data.idempotency_key},
            json={
                "items": [
                    {
                        "title": f"Pedido {request_data.order_code}",
                        "quantity": 1,
                        "unit_price": request_data.amount_cents / 100,
                        "currency_id": request_data.currency,
                    }
                ],
                "external_reference": request_data.order_code,
                "payer": (
                    {"email": request_data.customer_email}
                    if request_data.customer_email
                    else {}
                ),
                "notification_url": request_data.notification_url,
                "back_urls": {
                    "success": f"{public_url}/checkout/sucesso",
                    "pending": f"{public_url}/checkout/pendente",
                    "failure": f"{public_url}/checkout/falha",
                },
                "auto_return": "approved",
            },
        )
        checkout_url = preference.get("init_point") or preference.get("sandbox_init_point")
        return PaymentResult(
            status="pending",
            provider_reference=str(preference.get("id")) if preference.get("id") else None,
            checkout_url=checkout_url,
            metadata={"preference_id": preference.get("id")},
        )

    def authorize_auction(self, *, external_reference: str, amount_cents: int,
                          payer_email: str, card_token: str, payment_method_id: str,
                          installments: int, idempotency_key: str) -> PaymentResult:
        amount = f"{amount_cents / 100:.2f}"
        data = self._request(
            "POST", "/v1/orders",
            headers={"X-Idempotency-Key": idempotency_key},
            json={
                "capture_mode": "manual", "type": "online",
                "external_reference": external_reference, "processing_mode": "automatic",
                "marketplace": "NONE", "total_amount": amount,
                "payer": {"email": payer_email},
                "transactions": {"payments": [{"amount": amount, "payment_method": {
                    "id": payment_method_id, "type": "credit_card", "token": card_token,
                    "installments": installments,
                }}]},
            },
        )
        payments = data.get("transactions", {}).get("payments", [])
        payment = payments[0] if payments else {}
        status = "authorized" if payment.get("status_detail") == "waiting_capture" else "pending"
        return PaymentResult(status=status, provider_reference=str(data.get("id", "")), metadata={
            "payment_id": payment.get("id"), "status_detail": payment.get("status_detail"),
            "expires_at": data.get("date_created"),
        })

    def capture_auction(self, order_id: str, idempotency_key: str) -> PaymentResult:
        data = self._request("POST", f"/v1/orders/{order_id}/capture",
                             headers={"X-Idempotency-Key": idempotency_key})
        return PaymentResult(status="paid", provider_reference=order_id, metadata=data)

    def cancel_auction(self, order_id: str, idempotency_key: str) -> PaymentResult:
        data = self._request("POST", f"/v1/orders/{order_id}/cancel",
                             headers={"X-Idempotency-Key": idempotency_key})
        return PaymentResult(status="cancelled", provider_reference=order_id, metadata=data)

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        secret = str(current_app.config.get("PAYMENT_WEBHOOK_SECRET", ""))
        if not secret or not signature:
            return False
        try:
            parts = dict(item.split("=", 1) for item in signature.split(",") if "=" in item)
            timestamp = parts["ts"]
            received = parts["v1"]
        except (KeyError, ValueError):
            return False
        try:
            payload = json.loads(body or b"{}")
        except (TypeError, ValueError):
            payload = {}
        data_id = str(request.args.get("data.id") or payload.get("data", {}).get("id", ""))
        request_id = request.headers.get("x-request-id", "")
        manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
        expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, received)

    def parse_webhook(self, body: bytes) -> PaymentWebhook | None:
        try:
            payload = json.loads(body or b"{}")
        except (TypeError, ValueError):
            return None
        data_id = str(request.args.get("data.id") or payload.get("data", {}).get("id", ""))
        if not data_id:
            return None
        payment = self.reconcile(data_id)
        if not payment or not payment.metadata:
            return None
        return PaymentWebhook(
            provider_reference=data_id,
            status=payment.status,
            failure_code=payment.metadata.get("status_detail"),
            order_code=payment.metadata.get("external_reference"),
            amount_cents=payment.metadata.get("amount_cents"),
        )

    def refund(self, provider_reference: str, amount_cents: int | None = None) -> PaymentResult:
        body = {"amount": amount_cents / 100} if amount_cents is not None else {}
        result = self._request(
            "POST",
            f"/v1/payments/{provider_reference}/refunds",
            headers={"X-Idempotency-Key": f"refund-{provider_reference}-{amount_cents or 'full'}"},
            json=body,
        )
        return PaymentResult(
            status="refunded", provider_reference=str(result.get("id", provider_reference))
        )

    def reconcile(self, provider_reference: str) -> PaymentResult | None:
        data = self._request("GET", f"/v1/payments/{provider_reference}")
        status_map = {"approved": "paid", "pending": "pending", "in_process": "pending"}
        status = status_map.get(str(data.get("status")), "failed")
        return PaymentResult(
            status=status,
            provider_reference=provider_reference,
            metadata={
                "external_reference": data.get("external_reference"),
                "amount_cents": round(float(data.get("transaction_amount", 0)) * 100),
                "status_detail": data.get("status_detail"),
                "currency_id": data.get("currency_id"),
            },
        )


def apply_payment_webhook(event: PaymentWebhook) -> Payment | None:
    """Aplica uma transição confirmada pelo gateway em uma transação única."""
    payment = db.session.scalar(
        select(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(
            (Payment.provider_reference == event.provider_reference)
            | (Order.public_code == event.order_code)
        )
        .with_for_update()
    )
    if not payment:
        return None
    order = db.session.get(Order, payment.order_id)
    if not order:
        return None
    if event.amount_cents is not None and event.amount_cents != payment.amount_cents:
        raise MercadoPagoError("Valor do webhook diverge do valor do pedido")
    if event.status == "paid":
        if payment.status == "paid":
            return payment
        reservations = db.session.scalars(
            select(InventoryReservation)
            .where(
                InventoryReservation.order_id == order.id,
                InventoryReservation.status == "active",
            )
            .with_for_update()
        ).all()
        for reservation in reservations:
            variant = db.session.get(ProductVariant, reservation.variant_id)
            if not variant or variant.stock_quantity < reservation.quantity:
                raise MercadoPagoError("Estoque insuficiente para confirmar o pedido")
            variant.reserved_quantity -= reservation.quantity
            variant.stock_quantity -= reservation.quantity
            reservation.status = "committed"
            db.session.add(
                InventoryMovement(
                    variant_id=variant.id,
                    order_id=order.id,
                    quantity_delta=-reservation.quantity,
                    reason="payment_confirmed",
                    actor_user_id=None,
                    created_at=datetime.now(UTC),
                )
            )
        old_status = order.status
        payment.status = "paid"
        payment.provider_reference = event.provider_reference
        order.payment_status = "paid"
        order.status = "processing"
        db.session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=order.status,
                reason="Pagamento confirmado pelo Mercado Pago",
                created_at=datetime.now(UTC),
            )
        )
    elif event.status == "failed" and payment.status not in {"paid", "refunded"}:
        reservations = db.session.scalars(
            select(InventoryReservation)
            .where(
                InventoryReservation.order_id == order.id,
                InventoryReservation.status == "active",
            )
            .with_for_update()
        ).all()
        for reservation in reservations:
            variant = db.session.get(ProductVariant, reservation.variant_id)
            if variant:
                variant.reserved_quantity = max(
                    0, variant.reserved_quantity - reservation.quantity
                )
            reservation.status = "released"
        payment.status = "failed"
        payment.failure_code = (event.failure_code or "provider_rejected")[:80]
        order.payment_status = "failed"
        order.status = "cancelled"
    db.session.commit()
    return payment
