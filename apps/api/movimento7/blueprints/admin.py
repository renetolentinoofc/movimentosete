import platform
from datetime import UTC, datetime

from flask import Blueprint, current_app, g, request
from sqlalchemy import func, select, text

from ..extensions import db
from ..http import failure, success
from ..models import (
    AuctionLot,
    AuditLog,
    ContactMessage,
    GalleryMedia,
    Order,
    Product,
    ProductVariant,
    Registration,
    RegistrationStatusHistory,
)
from ..security import audit, require_permission
from ..validation import parse_uuid

bp = Blueprint("admin", __name__)


def paging() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 25))))
    except (TypeError, ValueError):
        return 1, 25
    return page, limit


@bp.get("/admin/dashboard")
@require_permission("dashboard.read")
def dashboard():
    counts = {
        "registrations_pending": db.session.scalar(
            select(func.count())
            .select_from(Registration)
            .where(Registration.status.in_(("received", "reviewing")))
        )
        or 0,
        "orders_pending": db.session.scalar(
            select(func.count()).select_from(Order).where(Order.status == "pending_payment")
        )
        or 0,
        "products": db.session.scalar(select(func.count()).select_from(Product)) or 0,
        "lots_open": db.session.scalar(
            select(func.count()).select_from(AuctionLot).where(AuctionLot.status == "open")
        )
        or 0,
        "gallery_processing": db.session.scalar(
            select(func.count())
            .select_from(GalleryMedia)
            .where(GalleryMedia.status == "processing")
        )
        or 0,
        "contacts_pending": db.session.scalar(
            select(func.count())
            .select_from(ContactMessage)
            .where(ContactMessage.status == "received")
        )
        or 0,
    }
    low_stock = db.session.execute(
        select(ProductVariant.sku, ProductVariant.stock_quantity, ProductVariant.reserved_quantity)
        .where(
            ProductVariant.active.is_(True),
            ProductVariant.stock_quantity - ProductVariant.reserved_quantity <= 3,
        )
        .limit(20)
    ).all()
    return success(
        {
            "counts": counts,
            "low_stock": [
                {"sku": row.sku, "available": row.stock_quantity - row.reserved_quantity}
                for row in low_stock
            ],
        }
    )


@bp.get("/admin/registrations")
@require_permission("registrations.read")
def registrations():
    page, limit = paging()
    query = select(Registration)
    status = request.args.get("status")
    if status in {"received", "reviewing", "approved", "waitlisted", "rejected", "withdrawn"}:
        query = query.where(Registration.status == status)
    search = request.args.get("q", "").strip()
    if search:
        query = query.where(Registration.full_name.ilike(f"%{search[:80]}%"))
    rows = db.session.scalars(
        query.order_by(Registration.created_at.desc()).offset((page - 1) * limit).limit(limit + 1)
    ).all()
    return success(
        [
            {
                "id": str(r.id),
                "protocol": r.protocol,
                "full_name": r.full_name,
                "professional_name": r.professional_name,
                "city": r.city,
                "status": r.status,
                "priority": r.priority,
                "created_at": r.created_at,
            }
            for r in rows[:limit]
        ],
        meta={"page": page, "limit": limit, "has_more": len(rows) > limit},
    )


@bp.patch("/admin/registrations/<registration_id>/status")
@require_permission("registrations.manage")
def registration_status(registration_id: str):
    body = request.get_json(silent=True) or {}
    new_status = str(body.get("status", ""))
    allowed = {"received", "reviewing", "approved", "waitlisted", "rejected", "withdrawn"}
    if new_status not in allowed:
        return failure(
            "validation_error",
            "Status inválido.",
            status=422,
            fields={"status": ["Escolha um status válido."]},
        )
    parsed_id = parse_uuid(registration_id)
    row = db.session.get(Registration, parsed_id) if parsed_id else None
    if not row:
        return failure("not_found", "Inscrição não encontrada.", status=404)
    old = row.status
    row.status = new_status
    db.session.add(
        RegistrationStatusHistory(
            registration_id=row.id,
            author_id=g.current_user.id,
            old_status=old,
            new_status=new_status,
            reason=str(body.get("reason", "")).strip() or None,
            created_at=datetime.now(UTC),
        )
    )
    audit(
        "registration.status_changed",
        "registration",
        f"Status alterado de {old} para {new_status}",
        str(row.id),
    )
    db.session.commit()
    return success({"id": str(row.id), "status": row.status})


@bp.get("/admin/audit-logs")
@require_permission("audit.read")
def audit_logs():
    page, limit = paging()
    rows = db.session.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit + 1)
    ).all()
    return success(
        [
            {
                "id": str(r.id),
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "summary": r.summary,
                "request_id": r.request_id,
                "created_at": r.created_at,
            }
            for r in rows[:limit]
        ],
        meta={"page": page, "limit": limit, "has_more": len(rows) > limit},
    )


@bp.get("/admin/system")
@require_permission("system.read")
def system():
    database_ok = False
    try:
        db.session.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        db.session.rollback()
    return success(
        {
            "app_version": current_app.config["APP_VERSION"],
            "git_commit": current_app.config["GIT_COMMIT"],
            "deployed_at": current_app.config["DEPLOYED_AT"],
            "environment": current_app.config["APP_ENV"],
            "python": platform.python_version(),
            "database": "connected" if database_ok else "unavailable",
            "drive": "configured"
            if current_app.config["MEDIA_PROVIDER"] == "google_drive"
            else "disabled",
            "payment_provider": current_app.config["PAYMENT_PROVIDER"],
            "auction_bidding_enabled": current_app.config["AUCTION_BIDDING_ENABLED"],
        }
    )
