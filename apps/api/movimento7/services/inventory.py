from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from ..extensions import db
from ..models import (
    Customer,
    InventoryReservation,
    Order,
    OrderStatusHistory,
    ProductVariant,
)
from .email_templates import order_status_update
from .order_notifications import notify_order


def expire_inventory_reservations(limit: int = 500) -> dict[str, int]:
    """Release unpaid inventory reservations whose checkout window has expired."""
    now = datetime.now(UTC)
    reservations = db.session.scalars(
        select(InventoryReservation)
        .where(
            InventoryReservation.status == "active",
            InventoryReservation.expires_at <= now,
        )
        .order_by(InventoryReservation.expires_at)
        .limit(limit)
        .with_for_update()
    ).all()
    affected_orders: set[UUID] = set()
    released_units = 0
    for reservation in reservations:
        variant = db.session.get(ProductVariant, reservation.variant_id)
        if variant:
            variant.reserved_quantity = max(0, variant.reserved_quantity - reservation.quantity)
        reservation.status = "expired"
        released_units += reservation.quantity
        affected_orders.add(reservation.order_id)

    expired_orders = 0
    expired_order_rows: list[Order] = []
    for order_id in affected_orders:
        order = db.session.get(Order, order_id)
        if not order or order.status != "pending_payment":
            continue
        has_active_reservation = db.session.scalar(
            select(InventoryReservation.id).where(
                InventoryReservation.order_id == order.id,
                InventoryReservation.status == "active",
            )
        )
        if has_active_reservation:
            continue
        old_status = order.status
        order.status = "expired"
        order.payment_status = "expired"
        db.session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=order.status,
                reason="Reserva de estoque expirada sem confirmação de pagamento",
                created_at=now,
            )
        )
        expired_orders += 1
        expired_order_rows.append(order)
    db.session.commit()
    for order in expired_order_rows:
        customer = db.session.get(Customer, order.customer_id)
        if customer:
            notify_order(
                order=order,
                template=order_status_update(
                    name=customer.name,
                    order_code=order.public_code,
                    status="expired",
                ),
            )
    if expired_order_rows:
        db.session.commit()
    return {
        "reservations_found": len(reservations),
        "released_units": released_units,
        "orders_expired": expired_orders,
    }
