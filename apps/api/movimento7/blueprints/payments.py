import logging

from flask import Blueprint, current_app, request
from sqlalchemy import select

from ..extensions import db
from ..http import failure, success
from ..models import Customer, Order, Payment
from ..services.email_templates import order_payment_update
from ..services.observability import capture_exception, capture_message
from ..services.order_notifications import format_order_total, notify_order
from ..services.payments import (
    MercadoPagoError,
    apply_payment_webhook,
    get_payment_provider,
)

bp = Blueprint("payments", __name__)
logger = logging.getLogger(__name__)


@bp.post("/payments/webhook/<provider>")
def payment_webhook(provider: str):
    if provider != current_app.config["PAYMENT_PROVIDER"]:
        return failure("provider_not_configured", "Provedor não configurado.", status=404)
    raw_body = request.get_data(cache=True)
    signature = request.headers.get("x-signature", "")
    gateway = get_payment_provider()
    if not gateway.verify_webhook(raw_body, signature):
        capture_message("Invalid payment webhook signature", context={"provider": provider})
        logger.warning("Invalid payment webhook signature", extra={"provider": provider})
        return failure("invalid_signature", "Assinatura inválida.", status=401)
    try:
        event = gateway.parse_webhook(raw_body)
        if not event:
            return failure("invalid_webhook", "Evento de pagamento inválido.", status=422)
        previous_status = db.session.scalar(
            select(Payment.status)
            .join(Order, Order.id == Payment.order_id)
            .where(
                (Payment.provider_reference == event.provider_reference)
                | (Order.public_code == event.order_code)
            )
        )
        payment = apply_payment_webhook(event)
        if not payment:
            return failure("payment_not_found", "Pagamento não encontrado.", status=404)
        order = db.session.get(Order, payment.order_id)
        customer = db.session.get(Customer, order.customer_id) if order else None
        if (
            order
            and customer
            and event.status in {"paid", "failed"}
            and previous_status != event.status
        ):
            notify_order(
                order=order,
                template=order_payment_update(
                    name=customer.name,
                    order_code=order.public_code,
                    status=event.status,
                    total=format_order_total(order.total_cents, order.currency),
                ),
            )
            db.session.commit()
    except MercadoPagoError as error:
        db.session.rollback()
        capture_exception(error, context={"component": "payment_webhook", "provider": provider})
        logger.exception("Payment webhook processing failed")
        return failure("webhook_processing_failed", str(error), status=409)
    return success({"received": True})
