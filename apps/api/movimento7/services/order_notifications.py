import logging
from datetime import datetime

from flask import g
from sqlalchemy import select

from ..extensions import db
from ..models import Customer, Order
from .communications import dispatch_email
from .email_templates import EmailTemplate

logger = logging.getLogger(__name__)


def notify_order(*, order: Order, template: EmailTemplate) -> str:
    """Dispatch an idempotent order notification without breaking the order flow."""
    customer = db.session.scalar(select(Customer).where(Customer.id == order.customer_id))
    if not customer or not customer.email:
        return "skipped"
    try:
        dispatch = dispatch_email(
            recipient=customer.email,
            template=template,
            idempotency_key=f"order:{order.id}:{template.key}",
        )
        return dispatch.status
    except Exception as error:
        logger.warning(
            "Order notification failed: %s (%s)",
            template.key,
            type(error).__name__,
            extra={"request_id": g.get("request_id")},
            exc_info=True,
        )
        return "failed"


def format_order_total(amount_cents: int, currency: str = "BRL") -> str:
    return (
        f"{currency} {amount_cents / 100:,.2f}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def format_order_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%d/%m/%Y às %H:%M")
