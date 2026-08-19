import json
import platform
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, current_app, g, request, send_file
from sqlalchemy import delete, func, select, text

from ..extensions import db
from ..http import failure, success
from ..models import (
    AdminUser,
    AuctionLot,
    AuditLog,
    CommunicationLog,
    ContactMessage,
    EventEdition,
    GalleryMedia,
    Order,
    ParticipationCategory,
    PortfolioAsset,
    Product,
    ProductVariant,
    Profile,
    ProfileCategory,
    Registration,
    RegistrationFile,
    RegistrationNote,
    RegistrationStatusHistory,
)
from ..security import audit, require_permission, sha256
from ..services.communications import dispatch_email
from ..services.email_delivery import deliver_email, email_configuration, mask_email, valid_email
from ..services.email_templates import registration_status_update
from ..services.media import LocalMediaProvider, process_portfolio_image
from ..validation import normalize_instagram, parse_uuid

bp = Blueprint("admin", __name__)


def paging() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 25))))
    except (TypeError, ValueError):
        return 1, 25
    return page, limit


def registration_or_none(registration_id: str) -> Registration | None:
    parsed = parse_uuid(registration_id)
    return db.session.get(Registration, parsed) if parsed else None


def profile_or_none(profile_id: str) -> Profile | None:
    parsed = parse_uuid(profile_id)
    return db.session.get(Profile, parsed) if parsed else None


def json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def profile_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    candidate = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return candidate[:160] or "artista"


def communication_log_data(item: CommunicationLog) -> dict[str, object]:
    return {
        "id": str(item.id),
        "channel": item.channel,
        "template_key": item.template_key,
        "status": item.status,
        "created_at": item.created_at,
    }


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


@bp.get("/admin/registrations/<registration_id>")
@require_permission("registrations.read")
def registration_detail(registration_id: str):
    row = registration_or_none(registration_id)
    if not row or row.deleted_at:
        return failure("not_found", "Inscrição não encontrada.", status=404)

    category = db.session.get(ParticipationCategory, row.category_id)
    edition = db.session.get(EventEdition, row.edition_id) if row.edition_id else None
    assigned = db.session.get(AdminUser, row.assigned_to_id) if row.assigned_to_id else None
    files = db.session.scalars(
        select(RegistrationFile)
        .where(RegistrationFile.registration_id == row.id)
        .order_by(RegistrationFile.created_at)
        .limit(100)
    ).all()
    note_rows = db.session.execute(
        select(RegistrationNote, AdminUser)
        .join(AdminUser, AdminUser.id == RegistrationNote.author_id)
        .where(RegistrationNote.registration_id == row.id)
        .order_by(RegistrationNote.pinned.desc(), RegistrationNote.created_at.desc())
        .limit(100)
    ).all()
    history_rows = db.session.execute(
        select(RegistrationStatusHistory, AdminUser)
        .outerjoin(AdminUser, AdminUser.id == RegistrationStatusHistory.author_id)
        .where(RegistrationStatusHistory.registration_id == row.id)
        .order_by(RegistrationStatusHistory.created_at.desc())
        .limit(100)
    ).all()
    assignees = db.session.scalars(
        select(AdminUser)
        .where(AdminUser.active.is_(True), AdminUser.deleted_at.is_(None))
        .order_by(AdminUser.name)
        .limit(100)
    ).all()
    profile = db.session.scalar(select(Profile).where(Profile.registration_id == row.id))

    return success(
        {
            "id": str(row.id),
            "protocol": row.protocol,
            "full_name": row.full_name,
            "professional_name": row.professional_name,
            "email": row.email,
            "phone": row.phone_e164,
            "instagram": row.instagram_handle,
            "city": row.city,
            "presentation": row.presentation,
            "portfolio_url": row.portfolio_url,
            "extra_data": json_object(row.extra_data_json),
            "status": row.status,
            "priority": row.priority,
            "assigned_to": (
                {"id": str(assigned.id), "name": assigned.name, "email": assigned.email}
                if assigned
                else None
            ),
            "category": (
                {"id": str(category.id), "name": category.name, "slug": category.slug}
                if category
                else None
            ),
            "edition": (
                {"id": str(edition.id), "name": edition.name, "slug": edition.slug}
                if edition
                else None
            ),
            "consent_at": row.consent_at,
            "privacy_version": row.privacy_version,
            "created_at": row.created_at,
            "files": [
                {
                    "id": str(item.id),
                    "name": item.original_name,
                    "mime_type": item.mime_type,
                    "size_bytes": item.size_bytes,
                    "width": item.width,
                    "height": item.height,
                    "status": item.processing_status,
                    "url": f"/api/v1/admin/registration-files/{item.id}",
                }
                for item in files
            ],
            "notes": [
                {
                    "id": str(note.id),
                    "body": note.body,
                    "pinned": note.pinned,
                    "created_at": note.created_at,
                    "author": {"id": str(author.id), "name": author.name},
                }
                for note, author in note_rows
            ],
            "history": [
                {
                    "id": str(item.id),
                    "old_status": item.old_status,
                    "new_status": item.new_status,
                    "reason": item.reason,
                    "created_at": item.created_at,
                    "author": (
                        {"id": str(author.id), "name": author.name} if author else None
                    ),
                }
                for item, author in history_rows
            ],
            "assignees": [
                {"id": str(item.id), "name": item.name, "email": item.email}
                for item in assignees
            ],
            "profile": (
                {"id": str(profile.id), "slug": profile.slug, "status": profile.status}
                if profile
                else None
            ),
        }
    )


@bp.patch("/admin/registrations/<registration_id>/triage")
@require_permission("registrations.manage")
def registration_triage(registration_id: str):
    row = registration_or_none(registration_id)
    if not row or row.deleted_at:
        return failure("not_found", "Inscrição não encontrada.", status=404)
    body = request.get_json(silent=True) or {}
    priority = str(body.get("priority", ""))
    if priority not in {"low", "normal", "high", "urgent"}:
        return failure(
            "validation_error",
            "Prioridade inválida.",
            status=422,
            fields={"priority": ["Escolha uma prioridade válida."]},
        )

    assigned_value = body.get("assigned_to_id")
    assigned = None
    if assigned_value:
        assigned_id = parse_uuid(assigned_value)
        assigned = db.session.get(AdminUser, assigned_id) if assigned_id else None
        if not assigned or not assigned.active or assigned.deleted_at:
            return failure(
                "validation_error",
                "Responsável inválido.",
                status=422,
                fields={"assigned_to_id": ["Escolha uma pessoa responsável ativa."]},
            )

    row.priority = priority
    row.assigned_to_id = assigned.id if assigned else None
    audit(
        "registration.triage_changed",
        "registration",
        f"Triagem atualizada: prioridade {priority}",
        str(row.id),
    )
    db.session.commit()
    return success(
        {
            "id": str(row.id),
            "priority": row.priority,
            "assigned_to": (
                {"id": str(assigned.id), "name": assigned.name, "email": assigned.email}
                if assigned
                else None
            ),
        }
    )


@bp.post("/admin/registrations/<registration_id>/notes")
@require_permission("registrations.manage")
def registration_note_create(registration_id: str):
    row = registration_or_none(registration_id)
    if not row or row.deleted_at:
        return failure("not_found", "Inscrição não encontrada.", status=404)
    body = request.get_json(silent=True) or {}
    note_body = str(body.get("body", "")).strip()
    if len(note_body) < 3 or len(note_body) > 2000:
        return failure(
            "validation_error",
            "A nota deve ter entre 3 e 2.000 caracteres.",
            status=422,
            fields={"body": ["Use entre 3 e 2.000 caracteres."]},
        )
    note = RegistrationNote(
        registration_id=row.id,
        author_id=g.current_user.id,
        body=note_body,
        pinned=body.get("pinned") is True,
    )
    db.session.add(note)
    db.session.flush()
    audit("registration.note_created", "registration", "Nota interna adicionada", str(row.id))
    db.session.commit()
    return success(
        {
            "id": str(note.id),
            "body": note.body,
            "pinned": note.pinned,
            "created_at": note.created_at,
            "author": {"id": str(g.current_user.id), "name": g.current_user.name},
        },
        status=201,
    )


@bp.post("/admin/registrations/<registration_id>/profile")
@require_permission("profiles.manage")
def registration_profile_create(registration_id: str):
    row = registration_or_none(registration_id)
    if not row or row.deleted_at:
        return failure("not_found", "Inscrição não encontrada.", status=404)
    if row.status != "approved":
        return failure(
            "invalid_state",
            "A inscrição precisa estar aprovada antes de criar o perfil.",
            status=409,
        )
    existing = db.session.scalar(select(Profile).where(Profile.registration_id == row.id))
    if existing:
        return failure("conflict", "Esta inscrição já possui um perfil.", status=409)

    base_slug = profile_slug(row.professional_name or row.full_name)
    slug = base_slug
    suffix = 2
    while db.session.scalar(select(Profile.id).where(Profile.slug == slug)):
        slug = f"{base_slug[:150]}-{suffix}"
        suffix += 1
    profile = Profile(
        registration_id=row.id,
        slug=slug,
        display_name=row.professional_name or row.full_name,
        bio=row.presentation,
        city=row.city,
        instagram_handle=row.instagram_handle,
        status="draft",
    )
    db.session.add(profile)
    db.session.flush()
    db.session.add(ProfileCategory(profile_id=profile.id, category_id=row.category_id))
    files = db.session.scalars(
        select(RegistrationFile)
        .where(
            RegistrationFile.registration_id == row.id,
            RegistrationFile.processing_status == "ready",
        )
        .order_by(RegistrationFile.created_at)
        .limit(30)
    ).all()
    for order, item in enumerate(files):
        db.session.add(
            PortfolioAsset(
                profile_id=profile.id,
                provider=item.provider,
                storage_key=item.storage_key,
                media_type="image",
                alt_text=f"Portfólio de {profile.display_name}",
                display_order=order,
                active=True,
            )
        )
    audit(
        "profile.created_from_registration",
        "profile",
        "Perfil em rascunho criado a partir de inscrição aprovada",
        str(profile.id),
    )
    db.session.commit()
    return success(
        {"id": str(profile.id), "slug": profile.slug, "status": profile.status}, status=201
    )


@bp.get("/admin/registration-files/<file_id>")
@require_permission("registrations.read")
def registration_file(file_id: str):
    parsed = parse_uuid(file_id)
    item = db.session.get(RegistrationFile, parsed) if parsed else None
    if not item:
        return failure("not_found", "Arquivo não encontrado.", status=404)
    if item.provider != "local":
        return failure(
            "provider_unavailable",
            "A visualização deste provedor ainda não está disponível.",
            status=409,
        )
    root = Path("instance/uploads/registrations").resolve()
    target = (root / item.storage_key).resolve()
    if root not in target.parents or not target.is_file():
        return failure("not_found", "Arquivo não encontrado.", status=404)
    return send_file(
        target,
        mimetype=item.mime_type,
        as_attachment=False,
        download_name=item.original_name,
        conditional=True,
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
    row = registration_or_none(registration_id)
    if not row:
        return failure("not_found", "Inscrição não encontrada.", status=404)
    old = row.status
    row.status = new_status
    history = RegistrationStatusHistory(
        registration_id=row.id,
        author_id=g.current_user.id,
        old_status=old,
        new_status=new_status,
        reason=str(body.get("reason", "")).strip() or None,
        created_at=datetime.now(UTC),
    )
    db.session.add(history)
    audit(
        "registration.status_changed",
        "registration",
        f"Status alterado de {old} para {new_status}",
        str(row.id),
    )
    db.session.commit()
    notification_status = "unavailable"
    if row.email and old != new_status:
        notification = dispatch_email(
            recipient=row.email,
            template=registration_status_update(
                name=row.full_name,
                protocol=row.protocol,
                status=new_status,
            ),
            idempotency_key=f"registration:{row.id}:status:{history.id}",
            registration_id=row.id,
            author_id=g.current_user.id,
        )
        notification_status = notification.status
        db.session.commit()
    return success(
        {"id": str(row.id), "status": row.status, "notification_status": notification_status}
    )


@bp.get("/admin/profiles")
@require_permission("profiles.manage")
def profiles_list():
    page, limit = paging()
    query = select(Profile)
    status = request.args.get("status", "").strip()
    if status in {"draft", "published", "archived"}:
        query = query.where(Profile.status == status)
    search = request.args.get("q", "").strip()
    if search:
        query = query.where(Profile.display_name.ilike(f"%{search[:80]}%"))
    rows = db.session.scalars(
        query.order_by(Profile.featured.desc(), Profile.updated_at.desc())
        .offset((page - 1) * limit)
        .limit(limit + 1)
    ).all()
    data = []
    for row in rows[:limit]:
        categories = db.session.scalars(
            select(ParticipationCategory.name)
            .join(ProfileCategory, ProfileCategory.category_id == ParticipationCategory.id)
            .where(ProfileCategory.profile_id == row.id)
            .order_by(ParticipationCategory.display_order)
        ).all()
        asset_count = db.session.scalar(
            select(func.count())
            .select_from(PortfolioAsset)
            .where(PortfolioAsset.profile_id == row.id, PortfolioAsset.active.is_(True))
        )
        data.append(
            {
                "id": str(row.id),
                "slug": row.slug,
                "display_name": row.display_name,
                "city": row.city,
                "status": row.status,
                "featured": row.featured,
                "categories": list(categories),
                "asset_count": int(asset_count or 0),
                "updated_at": row.updated_at,
                "published_at": row.published_at,
            }
        )
    return success(
        data,
        meta={"page": page, "limit": limit, "has_more": len(rows) > limit},
    )


@bp.get("/admin/profiles/<profile_id>")
@require_permission("profiles.manage")
def profile_admin_detail(profile_id: str):
    row = profile_or_none(profile_id)
    if not row:
        return failure("not_found", "Perfil não encontrado.", status=404)
    categories = db.session.scalars(
        select(ParticipationCategory)
        .join(ProfileCategory, ProfileCategory.category_id == ParticipationCategory.id)
        .where(ProfileCategory.profile_id == row.id)
        .order_by(ParticipationCategory.display_order)
    ).all()
    available_categories = db.session.scalars(
        select(ParticipationCategory)
        .where(ParticipationCategory.active.is_(True))
        .order_by(ParticipationCategory.display_order)
    ).all()
    assets = db.session.scalars(
        select(PortfolioAsset)
        .where(PortfolioAsset.profile_id == row.id)
        .order_by(PortfolioAsset.display_order, PortfolioAsset.created_at)
        .limit(100)
    ).all()
    registration = (
        db.session.get(Registration, row.registration_id) if row.registration_id else None
    )
    return success(
        {
            "id": str(row.id),
            "registration": (
                {"id": str(registration.id), "protocol": registration.protocol}
                if registration
                else None
            ),
            "slug": row.slug,
            "display_name": row.display_name,
            "bio": row.bio,
            "city": row.city,
            "instagram": row.instagram_handle,
            "status": row.status,
            "featured": row.featured,
            "published_at": row.published_at,
            "updated_at": row.updated_at,
            "category_ids": [str(item.id) for item in categories],
            "categories": [{"id": str(item.id), "name": item.name} for item in categories],
            "available_categories": [
                {"id": str(item.id), "name": item.name} for item in available_categories
            ],
            "assets": [
                {
                    "id": str(item.id),
                    "media_type": item.media_type,
                    "alt_text": item.alt_text,
                    "credit": item.credit,
                    "display_order": item.display_order,
                    "active": item.active,
                    "url": f"/api/v1/admin/profile-assets/{item.id}/file",
                }
                for item in assets
            ],
        }
    )


@bp.patch("/admin/profiles/<profile_id>")
@require_permission("profiles.manage")
def profile_admin_update(profile_id: str):
    row = profile_or_none(profile_id)
    if not row:
        return failure("not_found", "Perfil não encontrado.", status=404)
    body = request.get_json(silent=True) or {}
    display_name = str(body.get("display_name", "")).strip()
    slug = str(body.get("slug", "")).strip().lower()
    bio = str(body.get("bio", "")).strip()
    city = str(body.get("city", "")).strip()
    instagram_raw = str(body.get("instagram", "")).strip()
    instagram = normalize_instagram(instagram_raw)
    category_values = body.get("category_ids", [])
    fields: dict[str, list[str]] = {}
    if not display_name or len(display_name) > 140:
        fields["display_name"] = ["Informe um nome com até 140 caracteres."]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 180:
        fields["slug"] = ["Use letras minúsculas, números e hífens."]
    elif db.session.scalar(select(Profile.id).where(Profile.slug == slug, Profile.id != row.id)):
        fields["slug"] = ["Este endereço já está em uso."]
    if len(bio) < 10 or len(bio) > 5000:
        fields["bio"] = ["A biografia deve ter entre 10 e 5.000 caracteres."]
    if len(city) > 120:
        fields["city"] = ["Use no máximo 120 caracteres."]
    if instagram_raw and not instagram:
        fields["instagram"] = ["Informe apenas o usuário válido do Instagram."]
    if not isinstance(category_values, list) or not category_values:
        fields["category_ids"] = ["Selecione pelo menos uma categoria."]

    category_ids = (
        [parse_uuid(value) for value in category_values]
        if isinstance(category_values, list)
        else []
    )
    if any(value is None for value in category_ids):
        fields["category_ids"] = ["Uma das categorias é inválida."]
    categories = (
        db.session.scalars(
            select(ParticipationCategory).where(
                ParticipationCategory.id.in_([value for value in category_ids if value]),
                ParticipationCategory.active.is_(True),
            )
        ).all()
        if category_ids
        else []
    )
    if category_ids and len(categories) != len(set(category_ids)):
        fields["category_ids"] = ["Escolha apenas categorias disponíveis."]
    if fields:
        return failure("validation_error", "Revise os campos do perfil.", status=422, fields=fields)

    row.display_name = display_name
    row.slug = slug
    row.bio = bio
    row.city = city or None
    row.instagram_handle = instagram
    row.featured = body.get("featured") is True
    db.session.execute(delete(ProfileCategory).where(ProfileCategory.profile_id == row.id))
    db.session.add_all(
        [ProfileCategory(profile_id=row.id, category_id=category.id) for category in categories]
    )
    audit("profile.updated", "profile", "Perfil e categorias atualizados", str(row.id))
    db.session.commit()
    return success({"id": str(row.id), "slug": row.slug, "status": row.status})


@bp.patch("/admin/profiles/<profile_id>/status")
@require_permission("profiles.manage")
def profile_admin_status(profile_id: str):
    row = profile_or_none(profile_id)
    if not row:
        return failure("not_found", "Perfil não encontrado.", status=404)
    body = request.get_json(silent=True) or {}
    new_status = str(body.get("status", ""))
    if new_status not in {"draft", "published", "archived"}:
        return failure(
            "validation_error",
            "Status inválido.",
            status=422,
            fields={"status": ["Escolha um status válido."]},
        )
    category_count = db.session.scalar(
        select(func.count())
        .select_from(ProfileCategory)
        .where(ProfileCategory.profile_id == row.id)
    )
    if new_status == "published" and (not row.bio.strip() or not category_count):
        return failure(
            "profile_incomplete",
            "Complete a biografia e selecione uma categoria antes de publicar.",
            status=422,
        )
    old_status = row.status
    row.status = new_status
    if new_status == "published":
        row.published_at = datetime.now(UTC)
    audit(
        "profile.status_changed",
        "profile",
        f"Status alterado de {old_status} para {new_status}",
        str(row.id),
    )
    db.session.commit()
    return success(
        {
            "id": str(row.id),
            "slug": row.slug,
            "status": row.status,
            "published_at": row.published_at,
        }
    )


@bp.patch("/admin/profile-assets/<asset_id>")
@require_permission("profiles.manage")
def profile_asset_update(asset_id: str):
    parsed = parse_uuid(asset_id)
    row = db.session.get(PortfolioAsset, parsed) if parsed else None
    if not row:
        return failure("not_found", "Mídia não encontrada.", status=404)
    body = request.get_json(silent=True) or {}
    alt_text = str(body.get("alt_text", "")).strip()
    credit = str(body.get("credit", "")).strip()
    try:
        display_order = int(body.get("display_order", row.display_order))
    except (TypeError, ValueError):
        display_order = -1
    fields: dict[str, list[str]] = {}
    if len(alt_text) < 3 or len(alt_text) > 180:
        fields["alt_text"] = ["O texto alternativo deve ter entre 3 e 180 caracteres."]
    if len(credit) > 180:
        fields["credit"] = ["Use no máximo 180 caracteres."]
    if not 0 <= display_order <= 1000:
        fields["display_order"] = ["Use uma ordem entre 0 e 1.000."]
    if fields:
        return failure("validation_error", "Revise os dados da mídia.", status=422, fields=fields)
    row.alt_text = alt_text
    row.credit = credit or None
    row.display_order = display_order
    row.active = body.get("active") is not False
    audit("profile.asset_updated", "portfolio_asset", "Mídia do perfil atualizada", str(row.id))
    db.session.commit()
    return success(
        {
            "id": str(row.id),
            "alt_text": row.alt_text,
            "credit": row.credit,
            "display_order": row.display_order,
            "active": row.active,
        }
    )


@bp.post("/admin/profiles/<profile_id>/assets")
@require_permission("profiles.manage")
def profile_asset_create(profile_id: str):
    profile = profile_or_none(profile_id)
    if not profile:
        return failure("not_found", "Perfil não encontrado.", status=404)
    current_count = db.session.scalar(
        select(func.count())
        .select_from(PortfolioAsset)
        .where(PortfolioAsset.profile_id == profile.id)
    )
    if int(current_count or 0) >= 30:
        return failure(
            "portfolio_limit",
            "O portfólio pode ter no máximo 30 imagens.",
            status=409,
        )
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return failure(
            "validation_error",
            "Selecione uma imagem.",
            status=422,
            fields={"file": ["Envie uma imagem JPG, PNG ou WebP."]},
        )
    content = uploaded.read(12 * 1024 * 1024 + 1)
    if not content or len(content) > 12 * 1024 * 1024:
        return failure(
            "validation_error",
            "Arquivo inválido.",
            status=422,
            fields={"file": ["A imagem deve ter até 12 MB."]},
        )
    try:
        processed = process_portfolio_image(content)
    except ValueError:
        return failure(
            "validation_error",
            "Formato de imagem inválido.",
            status=422,
            fields={"file": ["Envie uma imagem JPG, PNG ou WebP válida."]},
        )
    alt_text = str(request.form.get("alt_text", "")).strip()
    credit = str(request.form.get("credit", "")).strip()
    if not alt_text:
        alt_text = f"Portfólio de {profile.display_name}"
    fields: dict[str, list[str]] = {}
    if not 3 <= len(alt_text) <= 180:
        fields["alt_text"] = ["O texto alternativo deve ter entre 3 e 180 caracteres."]
    if len(credit) > 180:
        fields["credit"] = ["Use no máximo 180 caracteres."]
    if fields:
        return failure("validation_error", "Revise os dados da mídia.", status=422, fields=fields)

    last_order = db.session.scalar(
        select(func.max(PortfolioAsset.display_order)).where(
            PortfolioAsset.profile_id == profile.id
        )
    )
    provider = LocalMediaProvider(Path("instance/uploads/registrations"))
    stored = provider.store(processed.content, processed.suffix, processed.mime_type)
    row = PortfolioAsset(
        profile_id=profile.id,
        provider=stored.provider,
        storage_key=stored.storage_key,
        media_type="image",
        alt_text=alt_text,
        credit=credit or None,
        display_order=int(last_order or 0) + (1 if current_count else 0),
        active=True,
    )
    try:
        db.session.add(row)
        db.session.flush()
        audit(
            "profile.asset_created",
            "portfolio_asset",
            f"Imagem {processed.width}x{processed.height} adicionada ao portfólio",
            str(row.id),
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        provider.delete(stored.storage_key)
        raise
    return success(
        {
            "id": str(row.id),
            "media_type": row.media_type,
            "alt_text": row.alt_text,
            "credit": row.credit,
            "display_order": row.display_order,
            "active": row.active,
            "width": processed.width,
            "height": processed.height,
            "url": f"/api/v1/admin/profile-assets/{row.id}/file",
        },
        status=201,
    )


@bp.patch("/admin/profiles/<profile_id>/assets/order")
@require_permission("profiles.manage")
def profile_assets_order(profile_id: str):
    profile = profile_or_none(profile_id)
    if not profile:
        return failure("not_found", "Perfil não encontrado.", status=404)
    body = request.get_json(silent=True) or {}
    supplied = body.get("asset_ids")
    assets = db.session.scalars(
        select(PortfolioAsset)
        .where(PortfolioAsset.profile_id == profile.id)
        .order_by(PortfolioAsset.display_order, PortfolioAsset.created_at)
    ).all()
    parsed = [parse_uuid(value) for value in supplied] if isinstance(supplied, list) else []
    expected = {item.id for item in assets}
    if (
        not isinstance(supplied, list)
        or len(parsed) != len(expected)
        or None in parsed
        or set(parsed) != expected
    ):
        return failure(
            "validation_error",
            "A ordem deve incluir todas as mídias do perfil uma única vez.",
            status=422,
            fields={"asset_ids": ["Revise a lista de mídias."]},
        )
    by_id = {item.id: item for item in assets}
    for display_order, asset_id in enumerate(parsed):
        if asset_id:
            by_id[asset_id].display_order = display_order
    audit("profile.assets_reordered", "profile", "Portfólio reordenado", str(profile.id))
    db.session.commit()
    return success({"asset_ids": [str(item) for item in parsed]})


@bp.post("/admin/profile-assets/<asset_id>/cover")
@require_permission("profiles.manage")
def profile_asset_cover(asset_id: str):
    parsed = parse_uuid(asset_id)
    target = db.session.get(PortfolioAsset, parsed) if parsed else None
    if not target:
        return failure("not_found", "Mídia não encontrada.", status=404)
    assets = db.session.scalars(
        select(PortfolioAsset)
        .where(PortfolioAsset.profile_id == target.profile_id)
        .order_by(PortfolioAsset.display_order, PortfolioAsset.created_at)
    ).all()
    ordered = [target, *[item for item in assets if item.id != target.id]]
    for display_order, item in enumerate(ordered):
        item.display_order = display_order
    target.active = True
    audit(
        "profile.asset_cover_changed",
        "portfolio_asset",
        "Imagem definida como capa do perfil",
        str(target.id),
    )
    db.session.commit()
    return success({"id": str(target.id), "display_order": 0, "active": True})


@bp.delete("/admin/profile-assets/<asset_id>")
@require_permission("profiles.manage")
def profile_asset_delete(asset_id: str):
    parsed = parse_uuid(asset_id)
    row = db.session.get(PortfolioAsset, parsed) if parsed else None
    if not row:
        return failure("not_found", "Mídia não encontrada.", status=404)
    storage_key = row.storage_key
    provider_name = row.provider
    shared_with_registration = bool(
        db.session.scalar(
            select(RegistrationFile.id).where(RegistrationFile.storage_key == storage_key)
        )
    )
    profile_id = row.profile_id
    audit(
        "profile.asset_deleted",
        "portfolio_asset",
        "Imagem removida do portfólio",
        str(row.id),
    )
    db.session.delete(row)
    db.session.commit()
    if provider_name == "local" and not shared_with_registration:
        LocalMediaProvider(Path("instance/uploads/registrations")).delete(storage_key)
    remaining = db.session.scalars(
        select(PortfolioAsset)
        .where(PortfolioAsset.profile_id == profile_id)
        .order_by(PortfolioAsset.display_order, PortfolioAsset.created_at)
    ).all()
    for display_order, item in enumerate(remaining):
        item.display_order = display_order
    db.session.commit()
    return success({"id": asset_id, "deleted": True})


@bp.get("/admin/profile-assets/<asset_id>/file")
@require_permission("profiles.manage")
def profile_asset_file(asset_id: str):
    parsed = parse_uuid(asset_id)
    item = db.session.get(PortfolioAsset, parsed) if parsed else None
    if not item:
        return failure("not_found", "Mídia não encontrada.", status=404)
    if item.provider != "local":
        return failure(
            "provider_unavailable",
            "A visualização deste provedor ainda não está disponível.",
            status=409,
        )
    root = Path("instance/uploads/registrations").resolve()
    target = (root / item.storage_key).resolve()
    if root not in target.parents or not target.is_file():
        return failure("not_found", "Mídia não encontrada.", status=404)
    return send_file(target, as_attachment=False, conditional=True)


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


@bp.get("/admin/communications")
@require_permission("communications.manage")
def communications():
    rows = db.session.scalars(
        select(CommunicationLog).order_by(CommunicationLog.created_at.desc()).limit(50)
    ).all()
    return success(
        {
            "configuration": email_configuration(),
            "recent": [communication_log_data(item) for item in rows],
        }
    )


@bp.post("/admin/communications/test")
@require_permission("communications.manage")
def test_communication():
    body = request.get_json(silent=True) or {}
    idempotency_key = str(body.get("idempotency_key", "")).strip()
    if not 8 <= len(idempotency_key) <= 100:
        return failure(
            "validation_error",
            "Informe uma chave de idempotência válida.",
            status=422,
            fields={"idempotency_key": ["Use entre 8 e 100 caracteres."]},
        )

    existing = db.session.scalar(
        select(CommunicationLog).where(
            CommunicationLog.idempotency_key == idempotency_key
        )
    )
    if existing:
        return success({**communication_log_data(existing), "duplicate": True})

    configuration = email_configuration()
    if not configuration["configured"]:
        return failure(
            "email_not_configured",
            "Complete a configuração SMTP antes de enviar o teste.",
            status=409,
        )

    recipient = str(body.get("recipient") or g.current_user.email).strip().lower()
    if not valid_email(recipient):
        return failure(
            "validation_error",
            "Informe um destinatário válido.",
            status=422,
            fields={"recipient": ["E-mail inválido."]},
        )

    subject = "Teste de configuração de e-mail — Movimento 7"
    text_body = (
        "Este é um teste controlado do painel Movimento 7.\n\n"
        "Se você recebeu esta mensagem, a configuração SMTP está funcionando.\n"
        "Nenhuma inscrição ou mensagem de produção foi enviada.\n"
    )
    now = datetime.now(UTC)
    try:
        delivery = deliver_email(recipient=recipient, subject=subject, text_body=text_body)
    except Exception as error:
        current_app.logger.warning(
            "Controlled email delivery failed: %s",
            type(error).__name__,
            extra={"request_id": g.request_id},
        )
        failed_target = (
            str(current_app.config["EMAIL_SANDBOX_RECIPIENT"])
            if configuration["mode"] == "sandbox"
            else recipient
        )
        log = CommunicationLog(
            author_id=g.current_user.id,
            channel="email",
            recipient_hash=sha256(failed_target),
            template_key="configuration_test",
            status="failed",
            idempotency_key=idempotency_key,
            created_at=now,
        )
        db.session.add(log)
        audit("communication.test_failed", "communication", "Teste de e-mail falhou")
        db.session.commit()
        return failure(
            "email_delivery_failed",
            "O provedor recusou o envio. Confira a senha de aplicativo e tente novamente.",
            status=502,
        )

    log = CommunicationLog(
        author_id=g.current_user.id,
        channel="email",
        recipient_hash=sha256(delivery.delivered_to),
        template_key="configuration_test",
        status=delivery.status,
        idempotency_key=idempotency_key,
        created_at=now,
    )
    db.session.add(log)
    audit("communication.test_sent", "communication", "Teste controlado de e-mail executado")
    db.session.commit()
    return success(
        {
            **communication_log_data(log),
            "delivered_to": mask_email(delivery.delivered_to),
            "duplicate": False,
        },
        status=201,
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
