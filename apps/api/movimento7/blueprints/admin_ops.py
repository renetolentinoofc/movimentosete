import base64
import hashlib
import json
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, current_app, g, redirect, request
from sqlalchemy import func, select
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..http import failure, success
from ..models import (
    Address,
    AdminUser,
    Artwork,
    AuctionLot,
    AuctionLotStatusHistory,
    ContentEntry,
    ContentVersion,
    Customer,
    EventEdition,
    Fulfillment,
    GalleryAlbum,
    GalleryMedia,
    IntegrationCredential,
    InventoryMovement,
    InventoryReservation,
    OAuthState,
    Order,
    OrderItem,
    OrderStatusHistory,
    Partner,
    Payment,
    PrivacyRequest,
    Product,
    ProductMedia,
    ProductVariant,
    Registration,
    Role,
)
from ..security import audit, require_permission, sha256
from ..services.email_templates import (
    order_payment_update as order_payment_email,
)
from ..services.email_templates import (
    order_status_update as order_status_email,
)
from ..services.media import (
    GoogleDriveMediaProvider,
    LocalMediaProvider,
    gallery_media_root,
    gallery_media_url,
    process_portfolio_image,
    reconcile_gallery_media,
)
from ..services.order_notifications import format_order_total, notify_order
from ..validation import aware_utc, parse_uuid, safe_http_url

bp = Blueprint("admin_ops", __name__)


@bp.get("/admin/auction-lots")
@require_permission("auction.manage")
def auction_lots_list():
    rows = db.session.execute(
        select(AuctionLot, Artwork).join(Artwork).order_by(AuctionLot.created_at.desc()).limit(100)
    ).all()
    return success(
        [
            {
                "id": str(lot.id),
                "slug": lot.slug,
                "title": lot.title,
                "artist_name": artwork.artist_name,
                "starting_bid_cents": lot.starting_bid_cents,
                "minimum_increment_cents": lot.minimum_increment_cents,
                "current_bid_cents": lot.current_bid_cents,
                "opens_at": lot.opens_at,
                "closes_at": lot.closes_at,
                "status": lot.status,
            }
            for lot, artwork in rows
        ]
    )


@bp.post("/admin/auction-lots")
@require_permission("auction.manage")
def auction_lot_create():
    body = body_json()
    title = str(body.get("title", "")).strip()
    slug = normalized_slug(str(body.get("slug") or title))
    artist_name = str(body.get("artist_name", "")).strip()
    try:
        starting_bid = int(body.get("starting_bid_cents", 0))
        increment = int(body.get("minimum_increment_cents", 0))
    except (TypeError, ValueError):
        starting_bid = increment = 0
    if not title or not slug or not artist_name or starting_bid < 0 or increment <= 0:
        return failure("validation_error", "Informe título, artista e valores válidos.", status=422)
    if db.session.scalar(select(AuctionLot.id).where(AuctionLot.slug == slug)):
        return failure("conflict", "Já existe um lote com este slug.", status=409)
    artwork = Artwork(
        title=title[:180],
        slug=f"{slug}-obra"[:180],
        artist_name=artist_name[:140],
        technique=str(body.get("technique", "")).strip()[:140] or None,
        dimensions=str(body.get("dimensions", "")).strip()[:120] or None,
        description=str(body.get("description", "")).strip() or None,
        status="draft",
    )
    db.session.add(artwork)
    db.session.flush()
    lot = AuctionLot(
        artwork_id=artwork.id,
        slug=slug,
        title=title[:180],
        rules=str(body.get("rules", "")).strip() or None,
        starting_bid_cents=starting_bid,
        minimum_increment_cents=increment,
        status="draft",
    )
    db.session.add(lot)
    audit("auction_lot.created", "auction_lot", "Lote de leilão criado", str(lot.id))
    db.session.commit()
    return success({"id": str(lot.id), "slug": lot.slug, "status": lot.status}, status=201)


@bp.patch("/admin/auction-lots/<lot_id>/status")
@require_permission("auction.manage")
def auction_lot_status(lot_id: str):
    parsed = parse_uuid(lot_id)
    lot = db.session.get(AuctionLot, parsed) if parsed else None
    if not lot:
        return failure("not_found", "Lote não encontrado.", status=404)
    new_status = str(body_json().get("status", "")).strip()
    transitions = {
        "draft": {"published", "archived"},
        "published": {"open", "archived"},
        "open": {"closed", "cancelled"},
        "closed": {"archived"},
        "cancelled": {"archived"},
        "archived": {"draft"},
    }
    if new_status not in transitions.get(lot.status, set()):
        return failure("invalid_transition", "Transição de status inválida.", status=409)
    old_status = lot.status
    lot.status = new_status
    db.session.add(
        AuctionLotStatusHistory(
            lot_id=lot.id,
            old_status=old_status,
            new_status=new_status,
            reason=str(body_json().get("reason", "")).strip()[:500] or None,
            actor_user_id=g.current_user.id,
            created_at=datetime.now(UTC),
        )
    )
    audit(
        "auction_lot.status_changed",
        "auction_lot",
        f"Status alterado de {old_status} para {new_status}",
        str(lot.id),
    )
    db.session.commit()
    return success({"id": str(lot.id), "status": lot.status})


@bp.patch("/admin/auction-lots/<lot_id>")
@require_permission("auction.manage")
def auction_lot_update(lot_id: str):
    lot = db.session.get(AuctionLot, parse_uuid(lot_id)) if parse_uuid(lot_id) else None
    if not lot:
        return failure("not_found", "Lote não encontrado.", status=404)
    artwork = db.session.get(Artwork, lot.artwork_id)
    body = body_json()
    slug = normalized_slug(str(body.get("slug", lot.slug)))
    if not slug or db.session.scalar(
        select(AuctionLot.id).where(AuctionLot.slug == slug, AuctionLot.id != lot.id)
    ):
        return failure("conflict", "Já existe um lote com este slug.", status=409)
    try:
        starting_bid = int(body.get("starting_bid_cents", lot.starting_bid_cents))
        increment = int(body.get("minimum_increment_cents", lot.minimum_increment_cents))
    except (TypeError, ValueError):
        return failure("validation_error", "Valores do lote inválidos.", status=422)
    if starting_bid < 0 or increment <= 0:
        return failure("validation_error", "Valores do lote inválidos.", status=422)
    lot.slug = slug
    lot.title = str(body.get("title", lot.title)).strip()[:180]
    lot.starting_bid_cents = starting_bid
    lot.minimum_increment_cents = increment
    lot.rules = str(body.get("rules", lot.rules or "")).strip() or None
    if artwork:
        artwork.title = lot.title
        artwork.artist_name = str(body.get("artist_name", artwork.artist_name)).strip()[:140]
        artwork.technique = (
            str(body.get("technique", artwork.technique or "")).strip()[:140] or None
        )
        artwork.dimensions = (
            str(body.get("dimensions", artwork.dimensions or "")).strip()[:120] or None
        )
        artwork.description = (
            str(body.get("description", artwork.description or "")).strip() or None
        )
    audit("auction_lot.updated", "auction_lot", "Lote de leilão atualizado", str(lot.id))
    db.session.commit()
    return success({"id": str(lot.id), "slug": lot.slug, "status": lot.status})


@bp.delete("/admin/auction-lots/<lot_id>")
@require_permission("auction.manage")
def auction_lot_delete(lot_id: str):
    lot = db.session.get(AuctionLot, parse_uuid(lot_id)) if parse_uuid(lot_id) else None
    if not lot:
        return failure("not_found", "Lote não encontrado.", status=404)
    lot.status = "archived"
    audit("auction_lot.archived", "auction_lot", "Lote de leilão arquivado", str(lot.id))
    db.session.commit()
    return success({"id": str(lot.id), "status": lot.status})


@bp.get("/admin/users")
@require_permission("users.manage")
def users_list():
    rows = db.session.scalars(select(AdminUser).order_by(AdminUser.name).limit(100)).all()
    return success(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "email": row.email,
                "active": row.active,
                "must_change_password": row.must_change_password,
                "roles": [role.slug for role in row.roles],
            }
            for row in rows
        ]
    )


@bp.post("/admin/users")
@require_permission("users.manage")
def user_create():
    body = body_json()
    email = str(body.get("email", "")).strip().lower()
    name = str(body.get("name", "")).strip()
    password = str(body.get("password", ""))
    role_slugs = body.get("roles", [])
    if (
        not email
        or "@" not in email
        or not name
        or len(password) < 12
        or not isinstance(role_slugs, list)
    ):
        return failure(
            "validation_error", "Informe nome, e-mail, senha forte e papéis.", status=422
        )
    if db.session.scalar(select(AdminUser.id).where(AdminUser.email == email)):
        return failure("conflict", "Já existe um usuário com este e-mail.", status=409)
    roles = db.session.scalars(select(Role).where(Role.slug.in_(role_slugs))).all()
    if len(roles) != len(set(role_slugs)):
        return failure("validation_error", "Um ou mais papéis não existem.", status=422)
    row = AdminUser(
        email=email[:180],
        name=name[:140],
        password_hash=generate_password_hash(password),
        must_change_password=True,
        roles=roles,
    )
    db.session.add(row)
    db.session.flush()
    audit("admin_user.created", "admin_user", "Usuário administrativo criado", str(row.id))
    db.session.commit()
    return success({"id": str(row.id), "email": row.email}, status=201)


@bp.patch("/admin/users/<user_id>")
@require_permission("users.manage")
def user_update(user_id: str):
    row = db.session.get(AdminUser, parse_uuid(user_id)) if parse_uuid(user_id) else None
    if not row:
        return failure("not_found", "Usuário não encontrado.", status=404)
    body = body_json()
    roles = body.get("roles")
    if roles is not None:
        if not isinstance(roles, list):
            return failure("validation_error", "Papéis inválidos.", status=422)
        assigned = db.session.scalars(select(Role).where(Role.slug.in_(roles))).all()
        if len(assigned) != len(set(roles)):
            return failure("validation_error", "Um ou mais papéis não existem.", status=422)
        row.roles = assigned
    if "name" in body and str(body["name"]).strip():
        row.name = str(body["name"]).strip()[:140]
    if "active" in body:
        if row.id == g.current_user.id and not body["active"]:
            return failure(
                "validation_error", "Não é possível desativar seu próprio usuário.", status=422
            )
        row.active = bool(body["active"])
        row.deleted_at = None if row.active else datetime.now(UTC)
        row.session_version += 1
    audit("admin_user.updated", "admin_user", "Usuário administrativo atualizado", str(row.id))
    db.session.commit()
    return success(
        {"id": str(row.id), "active": row.active, "roles": [role.slug for role in row.roles]}
    )


@bp.delete("/admin/users/<user_id>")
@require_permission("users.manage")
def user_delete(user_id: str):
    row = db.session.get(AdminUser, parse_uuid(user_id)) if parse_uuid(user_id) else None
    if not row:
        return failure("not_found", "Usuário não encontrado.", status=404)
    if row.id == g.current_user.id:
        return failure(
            "validation_error", "Não é possível desativar seu próprio usuário.", status=422
        )
    row.active = False
    row.deleted_at = datetime.now(UTC)
    row.session_version += 1
    audit("admin_user.archived", "admin_user", "Usuário administrativo desativado", str(row.id))
    db.session.commit()
    return success({"id": str(row.id), "active": row.active})


@bp.get("/admin/privacy/requests")
@require_permission("privacy.manage")
def privacy_requests_list():
    rows = db.session.scalars(
        select(PrivacyRequest).order_by(PrivacyRequest.created_at.desc()).limit(100)
    ).all()
    return success(
        [
            {
                "id": str(row.id),
                "protocol": row.protocol,
                "request_type": row.request_type,
                "status": row.status,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in rows
        ]
    )


@bp.patch("/admin/privacy/requests/<request_id>/status")
@require_permission("privacy.manage")
def privacy_request_status(request_id: str):
    parsed = parse_uuid(request_id)
    row = db.session.get(PrivacyRequest, parsed) if parsed else None
    if not row:
        return failure("not_found", "Solicitação de privacidade não encontrada.", status=404)
    status = str(body_json().get("status", "")).strip()
    if status not in {"received", "in_review", "resolved", "rejected"}:
        return failure("validation_error", "Status inválido.", status=422)
    row.status = status
    row.resolved_by_id = g.current_user.id if status in {"resolved", "rejected"} else None
    row.resolved_at = datetime.now(UTC) if status in {"resolved", "rejected"} else None
    audit(
        "privacy_request.status_changed",
        "privacy_request",
        "Status da solicitação LGPD alterado",
        str(row.id),
    )
    db.session.commit()
    return success({"id": str(row.id), "status": row.status, "resolved_at": row.resolved_at})


def gallery_album_data(row: GalleryAlbum) -> dict:
    return {
        "id": str(row.id),
        "edition_id": str(row.edition_id) if row.edition_id else None,
        "title": row.title,
        "slug": row.slug,
        "description": row.description,
        "status": row.status,
        "published_at": row.published_at,
    }


@bp.get("/admin/gallery/albums")
@require_permission("gallery.manage")
def gallery_albums_list():
    rows = db.session.scalars(
        select(GalleryAlbum).order_by(GalleryAlbum.created_at.desc()).limit(100)
    ).all()
    return success([gallery_album_data(row) for row in rows])


@bp.post("/admin/gallery/albums")
@require_permission("gallery.manage")
def gallery_album_create():
    body = body_json()
    title = str(body.get("title", "")).strip()
    slug = normalized_slug(str(body.get("slug") or title))
    description = str(body.get("description", "")).strip() or None
    if not 2 <= len(title) <= 180 or not slug:
        return failure("validation_error", "Informe um título válido para o álbum.", status=422)
    if db.session.scalar(select(GalleryAlbum.id).where(GalleryAlbum.slug == slug)):
        return failure("conflict", "Já existe um álbum com este slug.", status=409)
    row = GalleryAlbum(title=title, slug=slug, description=description, status="draft")
    db.session.add(row)
    audit("gallery.album_created", "gallery_album", "Álbum da galeria criado", str(row.id))
    db.session.commit()
    return success(gallery_album_data(row), status=201)


@bp.patch("/admin/gallery/albums/<album_id>/status")
@require_permission("gallery.manage")
def gallery_album_status(album_id: str):
    album = db.session.get(GalleryAlbum, parse_uuid(album_id)) if parse_uuid(album_id) else None
    if not album:
        return failure("not_found", "Álbum não encontrado.", status=404)
    status = str(body_json().get("status", "")).strip()
    if status not in {"draft", "published", "archived"}:
        return failure("validation_error", "Status do álbum inválido.", status=422)
    if status == "published":
        published_media = db.session.scalar(
            select(GalleryMedia.id).where(
                GalleryMedia.album_id == album.id,
                GalleryMedia.status == "published",
                GalleryMedia.deleted_at.is_(None),
            )
        )
        if not published_media:
            return failure(
                "validation_error",
                "Publique ao menos uma mídia antes de publicar o álbum.",
                status=422,
            )
        if not album.published_at:
            album.published_at = datetime.now(UTC)
    elif album.status == "published":
        album.published_at = None
    album.status = status
    audit(
        "gallery.album_status_changed", "gallery_album", "Status do álbum alterado", str(album.id)
    )
    db.session.commit()
    return success(gallery_album_data(album))


@bp.patch("/admin/gallery/albums/<album_id>")
@require_permission("gallery.manage")
def gallery_album_update(album_id: str):
    album = db.session.get(GalleryAlbum, parse_uuid(album_id)) if parse_uuid(album_id) else None
    if not album:
        return failure("not_found", "Álbum não encontrado.", status=404)
    body = body_json()
    slug = normalized_slug(str(body.get("slug", album.slug)))
    if not slug or db.session.scalar(
        select(GalleryAlbum.id).where(GalleryAlbum.slug == slug, GalleryAlbum.id != album.id)
    ):
        return failure("conflict", "Já existe um álbum com este slug.", status=409)
    title = str(body.get("title", album.title)).strip()
    if len(title) < 2:
        return failure("validation_error", "Informe um título válido para o álbum.", status=422)
    album.title = title[:180]
    album.slug = slug
    album.description = str(body.get("description", album.description or "")).strip() or None
    audit("gallery.album_updated", "gallery_album", "Álbum da galeria atualizado", str(album.id))
    db.session.commit()
    return success(gallery_album_data(album))


@bp.delete("/admin/gallery/albums/<album_id>")
@require_permission("gallery.manage")
def gallery_album_delete(album_id: str):
    album = db.session.get(GalleryAlbum, parse_uuid(album_id)) if parse_uuid(album_id) else None
    if not album:
        return failure("not_found", "Álbum não encontrado.", status=404)
    album.status = "archived"
    album.published_at = None
    audit("gallery.album_archived", "gallery_album", "Álbum da galeria arquivado", str(album.id))
    db.session.commit()
    return success(gallery_album_data(album))


@bp.patch("/admin/gallery/media/<media_id>/status")
@require_permission("gallery.manage")
def gallery_media_status(media_id: str):
    media = db.session.get(GalleryMedia, parse_uuid(media_id)) if parse_uuid(media_id) else None
    if not media or media.deleted_at:
        return failure("not_found", "Mídia não encontrada.", status=404)
    status = str(body_json().get("status", "")).strip()
    if status not in {"draft", "published", "archived"}:
        return failure("validation_error", "Status da mídia inválido.", status=422)
    media.status = status
    audit(
        "gallery.media_status_changed", "gallery_media", "Status da mídia alterado", str(media.id)
    )
    db.session.commit()
    return success(gallery_media_data(media))


@bp.patch("/admin/gallery/media/<media_id>")
@require_permission("gallery.manage")
def gallery_media_update(media_id: str):
    media = db.session.get(GalleryMedia, parse_uuid(media_id)) if parse_uuid(media_id) else None
    if not media or media.deleted_at:
        return failure("not_found", "Mídia não encontrada.", status=404)
    body = body_json()
    for field, limit in (
        ("title", 180),
        ("category", 60),
        ("caption", 600),
        ("alt_text", 180),
        ("credit", 180),
    ):
        if field in body:
            value = str(body[field]).strip()
            if field in {"title", "category", "alt_text"} and not value:
                return failure("validation_error", f"{field} é obrigatório.", status=422)
            setattr(media, field, value[:limit] or None)
    audit("gallery.media_updated", "gallery_media", "Mídia da galeria atualizada", str(media.id))
    db.session.commit()
    return success(gallery_media_data(media))


@bp.delete("/admin/gallery/media/<media_id>")
@require_permission("gallery.manage")
def gallery_media_delete(media_id: str):
    media = db.session.get(GalleryMedia, parse_uuid(media_id)) if parse_uuid(media_id) else None
    if not media or media.deleted_at:
        return failure("not_found", "Mídia não encontrada.", status=404)
    media.deleted_at = datetime.now(UTC)
    media.status = "archived"
    audit("gallery.media_archived", "gallery_media", "Mídia da galeria arquivada", str(media.id))
    db.session.commit()
    return success({"id": str(media.id), "status": media.status})


def gallery_media_data(row: GalleryMedia) -> dict:
    return {
        "id": str(row.id),
        "album_id": str(row.album_id),
        "category": row.category,
        "provider": row.provider,
        "url": gallery_media_url(row.provider, row.storage_key, str(row.id)),
        "media_type": row.media_type,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "width": row.width,
        "height": row.height,
        "title": row.title,
        "caption": row.caption,
        "alt_text": row.alt_text,
        "credit": row.credit,
        "display_order": row.display_order,
        "status": row.status,
        "reconciliation_status": row.reconciliation_status,
    }


@bp.get("/admin/gallery/albums/<album_id>/media")
@require_permission("gallery.manage")
def gallery_media_list(album_id: str):
    album = db.session.get(GalleryAlbum, parse_uuid(album_id)) if parse_uuid(album_id) else None
    if not album:
        return failure("not_found", "Álbum não encontrado.", status=404)
    rows = db.session.scalars(
        select(GalleryMedia)
        .where(GalleryMedia.album_id == album.id, GalleryMedia.deleted_at.is_(None))
        .order_by(GalleryMedia.display_order, GalleryMedia.created_at)
        .limit(200)
    ).all()
    return success([gallery_media_data(row) for row in rows])


@bp.post("/admin/gallery/albums/<album_id>/media/upload")
@require_permission("gallery.manage")
def gallery_media_upload(album_id: str):
    album = db.session.get(GalleryAlbum, parse_uuid(album_id)) if parse_uuid(album_id) else None
    uploaded = request.files.get("file")
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip()
    alt_text = request.form.get("alt_text", "").strip()
    if (
        not album
        or not uploaded
        or not uploaded.filename
        or not title
        or not category
        or not alt_text
    ):
        return failure(
            "validation_error",
            "Álbum, arquivo, título, categoria e texto alternativo são obrigatórios.",
            status=422,
        )
    try:
        processed = process_portfolio_image(uploaded.read())
        content_sha256 = hashlib.sha256(processed.content).hexdigest()
        if db.session.scalar(
            select(GalleryMedia.id).where(
                GalleryMedia.sha256 == content_sha256,
                GalleryMedia.deleted_at.is_(None),
            )
        ):
            return failure(
                "duplicate_media",
                "Esta imagem já está cadastrada na galeria.",
                status=409,
            )
        if current_app.config["MEDIA_PROVIDER"] == "google_drive":
            provider = GoogleDriveMediaProvider()
            stored = provider.store(
                processed.content,
                processed.suffix,
                processed.mime_type,
                folder_name=album.slug,
                root_folder_id=current_app.config["GOOGLE_DRIVE_GALLERY_FOLDER_ID"],
                filename_prefix="galeria",
            )
        else:
            provider = LocalMediaProvider(gallery_media_root())
            stored = provider.store(processed.content, processed.suffix, processed.mime_type)
    except (RuntimeError, ValueError) as error:
        return failure("media_upload_failed", str(error), status=422)
    media = GalleryMedia(
        album_id=album.id,
        category=category[:60],
        provider=stored.provider,
        provider_id=stored.provider_id,
        storage_key=stored.storage_key,
        safe_name=uploaded.filename[:255],
        media_type="image",
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        width=processed.width,
        height=processed.height,
        sha256=content_sha256,
        title=title[:180],
        caption=request.form.get("caption", "").strip()[:600] or None,
        alt_text=alt_text[:180],
        credit=request.form.get("credit", "").strip()[:180] or None,
        display_order=db.session.scalar(
            select(func.coalesce(func.max(GalleryMedia.display_order), -1) + 1).where(
                GalleryMedia.album_id == album.id, GalleryMedia.deleted_at.is_(None)
            )
        ),
        status="draft",
        reconciliation_status="completed",
    )
    db.session.add(media)
    audit("gallery_media.uploaded", "gallery_media", "Imagem da galeria enviada", str(media.id))
    db.session.commit()
    return success(gallery_media_data(media), status=201)


@bp.post("/admin/gallery/reconcile")
@bp.post("/admin/gallery/reconcile/retry")
@require_permission("gallery.manage")
def gallery_reconcile():
    try:
        summary = reconcile_gallery_media()
    except RuntimeError as error:
        db.session.rollback()
        return failure("reconciliation_failed", str(error), status=502)
    audit("gallery.reconciled", "gallery_media", "Reconciliação da galeria executada")
    db.session.commit()
    return success(summary)


def body_json() -> dict:
    return request.get_json(silent=True) or {}


def _release_order_reservations(order: Order, reason: str) -> None:
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
            variant.reserved_quantity = max(0, variant.reserved_quantity - reservation.quantity)
        reservation.status = "released"
        reservation.updated_at = datetime.now(UTC)
    audit("order.reservations_released", "order", reason, str(order.id))


def _commit_order_reservations(order: Order, reason: str) -> None:
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
            raise ValueError("Estoque insuficiente para confirmar o pedido.")
        variant.reserved_quantity -= reservation.quantity
        variant.stock_quantity -= reservation.quantity
        reservation.status = "committed"
        reservation.updated_at = datetime.now(UTC)
        db.session.add(
            InventoryMovement(
                variant_id=variant.id,
                order_id=order.id,
                quantity_delta=-reservation.quantity,
                reason=reason,
                actor_user_id=g.current_user.id,
                created_at=datetime.now(UTC),
            )
        )


def _order_data(order: Order, include_details: bool = False) -> dict:
    customer = db.session.get(Customer, order.customer_id)
    result = {
        "id": str(order.id),
        "order_code": order.public_code,
        "status": order.status,
        "payment_status": order.payment_status,
        "fulfillment_method": order.fulfillment_method,
        "subtotal_cents": order.subtotal_cents,
        "shipping_cents": order.shipping_cents,
        "total_cents": order.total_cents,
        "currency": order.currency,
        "created_at": order.created_at,
        "customer": {
            "name": customer.name if customer else "",
            "email": customer.email if customer else "",
            "phone": customer.phone_e164 if customer else "",
        },
    }
    if not include_details:
        return result
    address = db.session.get(Address, order.address_id) if order.address_id else None
    payment = db.session.scalar(
        select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at.desc())
    )
    fulfillment = db.session.scalar(
        select(Fulfillment)
        .where(Fulfillment.order_id == order.id)
        .order_by(Fulfillment.created_at.desc())
    )
    items = db.session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    history = db.session.scalars(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == order.id)
        .order_by(OrderStatusHistory.created_at.desc())
        .limit(50)
    ).all()
    result["address"] = (
        {
            "recipient_name": address.recipient_name,
            "postal_code": address.postal_code,
            "street": address.street,
            "number": address.number,
            "complement": address.complement,
            "neighborhood": address.neighborhood,
            "city": address.city,
            "state": address.state,
        }
        if address
        else None
    )
    result["items"] = [
        {
            "product_name": item.product_name_snapshot,
            "sku": item.sku_snapshot,
            "variant": item.variant_snapshot,
            "unit_price_cents": item.unit_price_cents,
            "quantity": item.quantity,
        }
        for item in items
    ]
    result["payment"] = (
        {
            "id": str(payment.id),
            "provider": payment.provider,
            "status": payment.status,
            "amount_cents": payment.amount_cents,
            "provider_reference": payment.provider_reference,
            "failure_code": payment.failure_code,
        }
        if payment
        else None
    )
    result["fulfillment"] = (
        {
            "id": str(fulfillment.id),
            "status": fulfillment.status,
            "carrier": fulfillment.carrier,
            "tracking_code": fulfillment.tracking_code,
            "shipped_at": fulfillment.shipped_at,
            "delivered_at": fulfillment.delivered_at,
        }
        if fulfillment
        else None
    )
    result["history"] = [
        {
            "old_status": item.old_status,
            "new_status": item.new_status,
            "reason": item.reason,
            "created_at": item.created_at,
        }
        for item in history
    ]
    return result


def normalized_slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")[:160]


def parsed_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return aware_utc(value).astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Data inválida") from None
    if parsed.tzinfo is None:
        raise ValueError("Informe o fuso horário")
    return parsed.astimezone(UTC)


def edition_values(body: dict, existing: EventEdition | None = None) -> tuple[dict, dict]:
    def current(name: str, default=None):
        return body[name] if name in body else getattr(existing, name, default)

    fields: dict[str, list[str]] = {}
    name = str(current("name", "") or "").strip()
    slug = normalized_slug(str(current("slug", "") or ""))
    description = str(current("description", "") or "").strip()
    location = str(current("location", "") or "").strip()
    address = str(current("address", "") or "").strip()
    map_input = str(current("map_url", "") or "").strip()
    map_url = safe_http_url(map_input) if map_input else None
    try:
        starts_at = parsed_datetime(current("starts_at"))
        ends_at = parsed_datetime(current("ends_at"))
        registration_opens_at = parsed_datetime(current("registration_opens_at"))
        registration_closes_at = parsed_datetime(current("registration_closes_at"))
    except ValueError as error:
        fields["dates"] = [str(error)]
        starts_at = ends_at = registration_opens_at = registration_closes_at = None
    raw_capacity = current("capacity")
    try:
        capacity = None if raw_capacity in (None, "") else int(raw_capacity)
    except (TypeError, ValueError):
        capacity = -1
    try:
        retention_days = int(current("retention_days", 730))
    except (TypeError, ValueError):
        retention_days = -1

    if not 2 <= len(name) <= 140:
        fields["name"] = ["Use entre 2 e 140 caracteres."]
    if not slug or len(slug) > 160:
        fields["slug"] = ["Informe um slug válido."]
    if len(description) > 5000:
        fields["description"] = ["Use no máximo 5.000 caracteres."]
    if len(location) > 180:
        fields["location"] = ["Use no máximo 180 caracteres."]
    if len(address) > 300:
        fields["address"] = ["Use no máximo 300 caracteres."]
    if map_input and not map_url:
        fields["map_url"] = ["Use um endereço http:// ou https:// válido."]
    if capacity is not None and not 1 <= capacity <= 100000:
        fields["capacity"] = ["Use uma capacidade entre 1 e 100.000."]
    if not 30 <= retention_days <= 3650:
        fields["retention_days"] = ["Use um período entre 30 e 3.650 dias."]
    if starts_at and ends_at and ends_at <= starts_at:
        fields["ends_at"] = ["O encerramento deve ocorrer depois do início."]
    if (
        registration_opens_at
        and registration_closes_at
        and registration_closes_at <= registration_opens_at
    ):
        fields["registration_closes_at"] = [
            "O encerramento das inscrições deve ocorrer depois da abertura."
        ]
    if registration_closes_at and starts_at and registration_closes_at > starts_at:
        fields["registration_closes_at"] = [
            "As inscrições devem encerrar antes do início do evento."
        ]
    return (
        {
            "name": name,
            "slug": slug,
            "description": description or None,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "registration_opens_at": registration_opens_at,
            "registration_closes_at": registration_closes_at,
            "location": location or None,
            "address": address or None,
            "map_url": map_url,
            "capacity": capacity,
            "retention_days": retention_days,
        },
        fields,
    )


def registration_count(edition_id) -> int:
    return int(
        db.session.scalar(
            select(func.count())
            .select_from(Registration)
            .where(Registration.edition_id == edition_id, Registration.deleted_at.is_(None))
        )
        or 0
    )


def edition_data(row: EventEdition) -> dict:
    count = registration_count(row.id)
    now = datetime.now(UTC)
    registration_open = bool(
        row.status == "published"
        and row.registration_opens_at
        and row.registration_closes_at
        and aware_utc(row.registration_opens_at) <= now <= aware_utc(row.registration_closes_at)
        and (row.capacity is None or count < row.capacity)
    )
    return {
        "id": str(row.id),
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "status": row.status,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "registration_opens_at": row.registration_opens_at,
        "registration_closes_at": row.registration_closes_at,
        "location": row.location,
        "address": row.address,
        "map_url": row.map_url,
        "capacity": row.capacity,
        "retention_days": row.retention_days,
        "published_at": row.published_at,
        "registration_count": count,
        "registration_open": registration_open,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def publication_fields(values: dict, edition_id) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for key in ("starts_at", "ends_at", "registration_opens_at", "registration_closes_at"):
        if not values[key]:
            fields[key] = ["Campo obrigatório para publicar."]
    if fields:
        return fields
    conflict = db.session.scalar(
        select(EventEdition).where(
            EventEdition.id != edition_id,
            EventEdition.status == "published",
            EventEdition.registration_opens_at < values["registration_closes_at"],
            EventEdition.registration_closes_at > values["registration_opens_at"],
        )
    )
    if conflict:
        fields["registration_opens_at"] = [
            f"A janela conflita com a edição publicada “{conflict.name}”."
        ]
    return fields


def assign_edition(row: EventEdition, values: dict) -> None:
    for key, value in values.items():
        setattr(row, key, value)


@bp.get("/admin/editions")
@require_permission("events.manage")
def editions_list():
    rows = db.session.scalars(
        select(EventEdition).order_by(EventEdition.created_at.desc()).limit(100)
    ).all()
    return success([edition_data(row) for row in rows])


@bp.post("/admin/editions")
@require_permission("events.manage")
def editions_create():
    body = body_json()
    values, fields = edition_values(body)
    if fields:
        return failure("validation_error", "Revise os dados da edição.", status=422, fields=fields)
    if db.session.scalar(select(EventEdition).where(EventEdition.slug == values["slug"])):
        return failure("conflict", "Já existe uma edição com este slug.", status=409)
    row = EventEdition(status="draft", **values)
    db.session.add(row)
    db.session.flush()
    audit("edition.created", "event_edition", "Edição criada", str(row.id))
    db.session.commit()
    return success(edition_data(row), status=201)


@bp.patch("/admin/editions/<edition_id>")
@require_permission("events.manage")
def edition_update(edition_id: str):
    parsed = parse_uuid(edition_id)
    row = db.session.get(EventEdition, parsed) if parsed else None
    if not row:
        return failure("not_found", "Edição não encontrada.", status=404)
    values, fields = edition_values(body_json(), row)
    duplicate = db.session.scalar(
        select(EventEdition).where(EventEdition.slug == values["slug"], EventEdition.id != row.id)
    )
    if duplicate:
        fields["slug"] = ["Este slug já pertence a outra edição."]
    count = registration_count(row.id)
    if values["capacity"] is not None and values["capacity"] < count:
        fields["capacity"] = [f"A capacidade não pode ser menor que as {count} inscrições atuais."]
    if row.status == "published":
        fields.update(publication_fields(values, row.id))
    if fields:
        return failure("validation_error", "Revise os dados da edição.", status=422, fields=fields)
    assign_edition(row, values)
    audit("edition.updated", "event_edition", "Edição atualizada", str(row.id))
    db.session.commit()
    return success(edition_data(row))


@bp.patch("/admin/editions/<edition_id>/status")
@require_permission("events.manage")
def edition_status(edition_id: str):
    parsed = parse_uuid(edition_id)
    row = db.session.get(EventEdition, parsed) if parsed else None
    if not row:
        return failure("not_found", "Edição não encontrada.", status=404)
    new_status = str(body_json().get("status", ""))
    transitions = {
        "draft": {"published", "archived"},
        "published": {"closed"},
        "closed": {"published", "archived"},
        "archived": {"draft"},
    }
    if new_status == row.status:
        return success(edition_data(row))
    if new_status not in transitions.get(row.status, set()):
        return failure(
            "invalid_transition",
            f"Não é possível alterar de {row.status} para {new_status}.",
            status=409,
        )
    if new_status == "published":
        values, fields = edition_values({}, row)
        fields.update(publication_fields(values, row.id))
        if fields:
            return failure(
                "edition_incomplete",
                "Complete e corrija a programação antes de publicar.",
                status=422,
                fields=fields,
            )
        if not row.published_at:
            row.published_at = datetime.now(UTC)
    old_status = row.status
    row.status = new_status
    audit(
        "edition.status_changed",
        "event_edition",
        f"Status alterado de {old_status} para {new_status}",
        str(row.id),
    )
    db.session.commit()
    return success(edition_data(row))


@bp.get("/admin/products")
@require_permission("store.manage")
def products_list():
    rows = db.session.scalars(select(Product).order_by(Product.created_at.desc()).limit(100)).all()
    return success(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "slug": row.slug,
                "description": row.description,
                "composition": row.composition,
                "price_cents": row.price_cents,
                "status": row.status,
                "featured": row.featured,
                "display_order": row.display_order,
                "variants": [
                    {
                        "id": str(variant.id),
                        "sku": variant.sku,
                        "name": variant.name,
                        "size": variant.size,
                        "color": variant.color,
                        "stock_quantity": variant.stock_quantity,
                        "reserved_quantity": variant.reserved_quantity,
                        "active": variant.active,
                    }
                    for variant in db.session.scalars(
                        select(ProductVariant)
                        .where(ProductVariant.product_id == row.id)
                        .order_by(ProductVariant.name)
                    ).all()
                ],
            }
            for row in rows
        ]
    )


@bp.post("/admin/products")
@require_permission("store.manage")
def products_create():
    body = body_json()
    try:
        price = int(body.get("price_cents", -1))
    except (TypeError, ValueError):
        price = -1
    if not body.get("name") or not body.get("slug") or price < 0:
        return failure(
            "validation_error", "Nome, slug e preço em centavos são obrigatórios.", status=422
        )
    row = Product(
        name=str(body["name"])[:180],
        slug=str(body["slug"])[:180],
        description=str(body.get("description", "")),
        composition=str(body.get("composition", "")) or None,
        price_cents=price,
        status="draft",
    )
    db.session.add(row)
    db.session.flush()
    audit("product.created", "product", "Produto criado", str(row.id))
    db.session.commit()
    return success({"id": str(row.id), "status": row.status}, status=201)


@bp.post("/admin/products/<product_id>/variants")
@require_permission("store.manage")
def variant_create(product_id: str):
    product = db.session.get(Product, parse_uuid(product_id)) if parse_uuid(product_id) else None
    body = body_json()
    if not product or not body.get("sku") or not body.get("name"):
        return failure("validation_error", "Produto, SKU e nome são obrigatórios.", status=422)
    try:
        stock = max(0, int(body.get("stock_quantity", 0)))
    except (TypeError, ValueError):
        stock = 0
    row = ProductVariant(
        product_id=product.id,
        sku=str(body["sku"])[:80],
        name=str(body["name"])[:120],
        size=str(body.get("size", "")) or None,
        color=str(body.get("color", "")) or None,
        stock_quantity=stock,
    )
    db.session.add(row)
    audit(
        "variant.created", "product_variant", "Variação e estoque inicial cadastrados", str(row.id)
    )
    db.session.commit()
    return success({"id": str(row.id), "stock_quantity": row.stock_quantity}, status=201)


@bp.post("/admin/products/<product_id>/media")
@require_permission("store.manage")
def product_media_create(product_id: str):
    product = db.session.get(Product, parse_uuid(product_id)) if parse_uuid(product_id) else None
    body = body_json()
    storage_key = str(body.get("storage_key", "")).strip()
    alt_text = str(body.get("alt_text", "")).strip()
    if not product or not storage_key or not alt_text:
        return failure(
            "validation_error",
            "Produto, endereço da imagem e texto alternativo são obrigatórios.",
            status=422,
        )
    media = ProductMedia(
        product_id=product.id,
        provider=str(body.get("provider", "local"))[:30],
        storage_key=storage_key[:500],
        alt_text=alt_text[:180],
        width=int(body["width"]) if body.get("width") else None,
        height=int(body["height"]) if body.get("height") else None,
    )
    db.session.add(media)
    audit("product_media.created", "product_media", "Mídia de produto cadastrada", str(media.id))
    db.session.commit()
    return success({"id": str(media.id), "storage_key": media.storage_key}, status=201)


@bp.post("/admin/products/<product_id>/media/upload")
@require_permission("store.manage")
def product_media_upload(product_id: str):
    product = db.session.get(Product, parse_uuid(product_id)) if parse_uuid(product_id) else None
    uploaded = request.files.get("file")
    alt_text = request.form.get("alt_text", "").strip()
    if not product or not uploaded or not uploaded.filename or not alt_text:
        return failure(
            "validation_error",
            "Produto, arquivo e texto alternativo são obrigatórios.",
            status=422,
        )
    try:
        processed = process_portfolio_image(uploaded.read())
        provider = (
            GoogleDriveMediaProvider()
            if current_app.config["MEDIA_PROVIDER"] == "google_drive"
            else LocalMediaProvider(Path("instance/uploads/products"))
        )
        if isinstance(provider, GoogleDriveMediaProvider):
            stored = provider.store(
                processed.content, processed.suffix, processed.mime_type, folder_name=product.slug
            )
        else:
            stored = provider.store(processed.content, processed.suffix, processed.mime_type)
    except (RuntimeError, ValueError) as error:
        return failure("media_upload_failed", str(error), status=422)
    media = ProductMedia(
        product_id=product.id,
        provider=stored.provider,
        storage_key=stored.storage_key,
        alt_text=alt_text[:180],
        width=processed.width,
        height=processed.height,
    )
    db.session.add(media)
    audit("product_media.uploaded", "product_media", "Imagem de produto enviada", str(media.id))
    db.session.commit()
    return success(
        {"id": str(media.id), "url": media.storage_key, "provider": media.provider},
        status=201,
    )


@bp.patch("/admin/products/<product_id>")
@require_permission("store.manage")
def product_update(product_id: str):
    product = db.session.get(Product, parse_uuid(product_id)) if parse_uuid(product_id) else None
    if not product:
        return failure("not_found", "Produto não encontrado.", status=404)
    body = body_json()
    name = str(body.get("name", product.name)).strip()
    slug = normalized_slug(str(body.get("slug", product.slug)))
    try:
        price = int(body.get("price_cents", product.price_cents))
    except (TypeError, ValueError):
        return failure("validation_error", "Preço inválido.", status=422)
    if not name or not slug or price < 0:
        return failure("validation_error", "Nome, slug e preço são obrigatórios.", status=422)
    if db.session.scalar(select(Product.id).where(Product.slug == slug, Product.id != product.id)):
        return failure("conflict", "Já existe um produto com este slug.", status=409)
    product.name = name[:180]
    product.slug = slug
    product.description = str(body.get("description", product.description)).strip()
    product.composition = str(body.get("composition", product.composition or "")).strip() or None
    product.price_cents = price
    product.featured = bool(body.get("featured", product.featured))
    try:
        product.display_order = int(body.get("display_order", product.display_order))
    except (TypeError, ValueError):
        return failure("validation_error", "Ordem de exibição inválida.", status=422)
    audit("product.updated", "product", "Produto atualizado", str(product.id))
    db.session.commit()
    return success({"id": str(product.id), "slug": product.slug, "status": product.status})


@bp.patch("/admin/products/<product_id>/status")
@require_permission("store.manage")
def product_status(product_id: str):
    product = db.session.get(Product, parse_uuid(product_id)) if parse_uuid(product_id) else None
    if not product:
        return failure("not_found", "Produto não encontrado.", status=404)
    new_status = str(body_json().get("status", "")).strip()
    transitions = {
        "draft": {"published", "archived"},
        "published": {"draft", "archived"},
        "archived": {"draft"},
    }
    if new_status not in transitions.get(product.status, set()):
        return failure("invalid_transition", "Transição de produto inválida.", status=409)
    if new_status == "published":
        has_variant = db.session.scalar(
            select(ProductVariant.id).where(
                ProductVariant.product_id == product.id, ProductVariant.active.is_(True)
            )
        )
        has_media = db.session.scalar(
            select(ProductMedia.id).where(
                ProductMedia.product_id == product.id, ProductMedia.active.is_(True)
            )
        )
        if not has_variant or not has_media:
            return failure(
                "product_incomplete",
                "Adicione ao menos uma variante e uma imagem antes de publicar.",
                status=422,
            )
    old_status = product.status
    product.status = new_status
    audit(
        "product.status_changed",
        "product",
        f"Status alterado de {old_status} para {new_status}",
        str(product.id),
    )
    db.session.commit()
    return success({"id": str(product.id), "status": product.status})


@bp.patch("/admin/products/<product_id>/variants/<variant_id>")
@require_permission("store.manage")
def product_variant_update(product_id: str, variant_id: str):
    product = db.session.get(Product, parse_uuid(product_id)) if parse_uuid(product_id) else None
    variant = (
        db.session.get(ProductVariant, parse_uuid(variant_id)) if parse_uuid(variant_id) else None
    )
    if not product or not variant or variant.product_id != product.id:
        return failure("not_found", "Variante não encontrada.", status=404)
    body = body_json()
    sku = str(body.get("sku", variant.sku)).strip()
    name = str(body.get("name", variant.name)).strip()
    try:
        stock = int(body.get("stock_quantity", variant.stock_quantity))
    except (TypeError, ValueError):
        return failure("validation_error", "Estoque inválido.", status=422)
    if not sku or not name or stock < variant.reserved_quantity:
        return failure(
            "validation_error",
            "Informe SKU, nome e estoque maior ou igual ao reservado.",
            status=422,
        )
    if db.session.scalar(
        select(ProductVariant.id).where(ProductVariant.sku == sku, ProductVariant.id != variant.id)
    ):
        return failure("conflict", "Já existe uma variante com este SKU.", status=409)
    delta = stock - variant.stock_quantity
    variant.sku = sku[:80]
    variant.name = name[:120]
    variant.size = str(body.get("size", variant.size or "")).strip() or None
    variant.color = str(body.get("color", variant.color or "")).strip() or None
    variant.active = bool(body.get("active", variant.active))
    if body.get("price_override_cents") is not None:
        try:
            variant.price_override_cents = int(body["price_override_cents"])
        except (TypeError, ValueError):
            return failure("validation_error", "Preço da variante inválido.", status=422)
    variant.stock_quantity = stock
    if delta:
        db.session.add(
            InventoryMovement(
                variant_id=variant.id,
                quantity_delta=delta,
                reason="admin_stock_adjustment",
                actor_user_id=g.current_user.id,
                created_at=datetime.now(UTC),
            )
        )
    audit("product_variant.updated", "product_variant", "Variante atualizada", str(variant.id))
    db.session.commit()
    return success(
        {
            "id": str(variant.id),
            "stock_quantity": variant.stock_quantity,
            "reserved_quantity": variant.reserved_quantity,
        }
    )


@bp.get("/admin/inventory/movements")
@require_permission("store.manage")
def inventory_movements_list():
    variant_id = parse_uuid(request.args.get("variant_id", ""))
    try:
        limit = min(200, max(1, int(request.args.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100
    query = (
        select(InventoryMovement, ProductVariant, Product)
        .join(ProductVariant, ProductVariant.id == InventoryMovement.variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(limit)
    )
    if variant_id:
        query = query.where(InventoryMovement.variant_id == variant_id)
    rows = db.session.execute(query).all()
    return success(
        [
            {
                "id": str(movement.id),
                "product_id": str(product.id),
                "product_name": product.name,
                "variant_id": str(variant.id),
                "variant_name": variant.name,
                "sku": variant.sku,
                "quantity_delta": movement.quantity_delta,
                "reason": movement.reason,
                "created_at": movement.created_at,
            }
            for movement, variant, product in rows
        ]
    )


@bp.get("/admin/orders")
@require_permission("orders.manage")
def orders_list():
    status = str(request.args.get("status", "")).strip()
    query = (
        select(Order, Customer)
        .join(Customer, Customer.id == Order.customer_id)
        .order_by(Order.created_at.desc())
        .limit(200)
    )
    if status:
        query = query.where(Order.status == status)
    rows = db.session.execute(query).all()
    return success(
        [
            {
                **_order_data(order),
                "customer": {
                    "name": customer.name,
                    "email": customer.email,
                    "phone": customer.phone_e164,
                },
            }
            for order, customer in rows
        ]
    )


@bp.get("/admin/orders/<order_id>")
@require_permission("orders.manage")
def order_detail(order_id: str):
    order = db.session.get(Order, parse_uuid(order_id)) if parse_uuid(order_id) else None
    if not order:
        return failure("not_found", "Pedido não encontrado.", status=404)
    return success(_order_data(order, include_details=True))


@bp.patch("/admin/orders/<order_id>/payment")
@require_permission("payments.manage")
def order_payment_update(order_id: str):
    order = db.session.get(Order, parse_uuid(order_id)) if parse_uuid(order_id) else None
    if not order:
        return failure("not_found", "Pedido não encontrado.", status=404)
    payment = db.session.scalar(
        select(Payment)
        .where(Payment.order_id == order.id)
        .order_by(Payment.created_at.desc())
        .with_for_update()
    )
    if not payment:
        return failure("not_found", "Pagamento não encontrado.", status=404)
    new_status = str(body_json().get("status", "")).strip()
    if new_status not in {"paid", "failed", "refunded"}:
        return failure("validation_error", "Status de pagamento inválido.", status=422)
    if payment.status == "paid" and new_status == "paid":
        return success(_order_data(order, include_details=True))
    if payment.status in {"refunded", "failed"}:
        return failure("invalid_transition", "Pagamento já encerrado.", status=409)
    customer = db.session.get(Customer, order.customer_id)
    notification_template = None
    if new_status == "paid":
        try:
            _commit_order_reservations(order, "payment_confirmed")
        except ValueError as error:
            db.session.rollback()
            return failure("out_of_stock", str(error), status=409)
        payment.status = "paid"
        order.payment_status = "paid"
        old_status = order.status
        order.status = "processing"
        db.session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=order.status,
                reason="Pagamento confirmado pela equipe",
                actor_user_id=g.current_user.id,
                created_at=datetime.now(UTC),
            )
        )
        notification_template = order_payment_email(
            name=customer.name if customer else "cliente",
            order_code=order.public_code,
            status="paid",
            total=format_order_total(order.total_cents, order.currency),
        )
    elif new_status == "failed":
        payment.status = "failed"
        payment.failure_code = str(body_json().get("failure_code", "manual_review"))[:80]
        order.payment_status = "failed"
        _release_order_reservations(order, "Pagamento não confirmado")
        old_status = order.status
        order.status = "cancelled"
        db.session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=order.status,
                reason="Pagamento não confirmado",
                actor_user_id=g.current_user.id,
                created_at=datetime.now(UTC),
            )
        )
        notification_template = order_payment_email(
            name=customer.name if customer else "cliente",
            order_code=order.public_code,
            status="failed",
            total=format_order_total(order.total_cents, order.currency),
        )
    else:
        if payment.status != "paid":
            return failure(
                "invalid_transition", "Só pagamentos confirmados podem ser estornados.", status=409
            )
        payment.status = "refunded"
        order.payment_status = "refunded"
        order.status = "cancelled"
        notification_template = order_payment_email(
            name=customer.name if customer else "cliente",
            order_code=order.public_code,
            status="refunded",
            total=format_order_total(order.total_cents, order.currency),
        )
    audit(
        "order.payment_status_changed",
        "payment",
        f"Pagamento alterado para {new_status}",
        str(payment.id),
    )
    db.session.commit()
    if notification_template:
        notify_order(order=order, template=notification_template)
        db.session.commit()
    return success(_order_data(order, include_details=True))


@bp.patch("/admin/orders/<order_id>/status")
@require_permission("orders.manage")
def order_status_update(order_id: str):
    order = db.session.get(Order, parse_uuid(order_id)) if parse_uuid(order_id) else None
    if not order:
        return failure("not_found", "Pedido não encontrado.", status=404)
    new_status = str(body_json().get("status", "")).strip()
    transitions = {
        "pending_payment": {"cancelled"},
        "processing": {"shipped", "cancelled"},
        "shipped": {"delivered"},
    }
    if new_status not in transitions.get(order.status, set()):
        return failure("invalid_transition", "Transição de pedido inválida.", status=409)
    if new_status == "cancelled" and order.payment_status == "paid":
        return failure(
            "payment_refund_required", "Estorne o pagamento antes de cancelar o pedido.", status=409
        )
    old_status = order.status
    order.status = new_status
    customer = db.session.get(Customer, order.customer_id)
    notification_template = None
    if new_status == "cancelled":
        _release_order_reservations(order, "Pedido cancelado pela equipe")
    if new_status == "shipped":
        fulfillment = db.session.scalar(select(Fulfillment).where(Fulfillment.order_id == order.id))
        if not fulfillment:
            fulfillment = Fulfillment(order_id=order.id, status="shipped")
            db.session.add(fulfillment)
        fulfillment.status = "shipped"
        fulfillment.shipped_at = datetime.now(UTC)
    if new_status == "delivered":
        fulfillment = db.session.scalar(select(Fulfillment).where(Fulfillment.order_id == order.id))
        if not fulfillment:
            fulfillment = Fulfillment(order_id=order.id, status="delivered")
            db.session.add(fulfillment)
        fulfillment.status = "delivered"
        fulfillment.delivered_at = datetime.now(UTC)
    if new_status in {"shipped", "delivered"}:
        notification_template = order_status_email(
            name=customer.name if customer else "cliente",
            order_code=order.public_code,
            status=new_status,
        )
    db.session.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            reason=str(body_json().get("reason", "")).strip()[:500] or None,
            actor_user_id=g.current_user.id,
            created_at=datetime.now(UTC),
        )
    )
    audit(
        "order.status_changed",
        "order",
        f"Status alterado de {old_status} para {new_status}",
        str(order.id),
    )
    db.session.commit()
    if notification_template:
        notify_order(order=order, template=notification_template)
        db.session.commit()
    return success(_order_data(order, include_details=True))


@bp.patch("/admin/orders/<order_id>/fulfillment")
@require_permission("orders.manage")
def order_fulfillment_update(order_id: str):
    order = db.session.get(Order, parse_uuid(order_id)) if parse_uuid(order_id) else None
    if not order:
        return failure("not_found", "Pedido não encontrado.", status=404)
    body = body_json()
    fulfillment = db.session.scalar(select(Fulfillment).where(Fulfillment.order_id == order.id))
    if not fulfillment:
        fulfillment = Fulfillment(order_id=order.id, status="pending")
        db.session.add(fulfillment)
    fulfillment.carrier = str(body.get("carrier", fulfillment.carrier or "")).strip()[:100] or None
    fulfillment.tracking_code = (
        str(body.get("tracking_code", fulfillment.tracking_code or "")).strip()[:100] or None
    )
    audit("order.fulfillment_updated", "fulfillment", "Entrega atualizada", str(fulfillment.id))
    db.session.commit()
    return success(_order_data(order, include_details=True))


@bp.get("/admin/partners")
@require_permission("partners.manage")
def partners_list():
    rows = db.session.scalars(
        select(Partner)
        .where(Partner.deleted_at.is_(None))
        .order_by(Partner.display_order)
        .limit(100)
    ).all()
    return success(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "slug": row.slug,
                "active": row.active,
                "category": row.category,
                "level": row.level,
                "logo_path": row.logo_path,
                "logo_alt": row.logo_alt,
                "website_url": row.website_url,
            }
            for row in rows
        ]
    )


@bp.post("/admin/partners")
@require_permission("partners.manage")
def partner_create():
    body = body_json()
    website = safe_http_url(str(body.get("website_url", "")))
    if not body.get("name") or not body.get("slug") or not body.get("logo_path"):
        return failure("validation_error", "Nome, slug e logo são obrigatórios.", status=422)
    row = Partner(
        name=str(body["name"])[:140],
        slug=str(body["slug"])[:160],
        logo_path=str(body["logo_path"])[:500],
        logo_alt=str(body.get("logo_alt", f"Logo {body['name']}"))[:180],
        website_url=website,
        category=str(body.get("category", "parceiro"))[:60],
        level=str(body.get("level", ""))[:60] or None,
    )
    db.session.add(row)
    audit("partner.created", "partner", "Parceiro criado", str(row.id))
    db.session.commit()
    return success({"id": str(row.id)}, status=201)


@bp.patch("/admin/partners/<partner_id>")
@require_permission("partners.manage")
def partner_update(partner_id: str):
    row = db.session.get(Partner, parse_uuid(partner_id)) if parse_uuid(partner_id) else None
    if not row or row.deleted_at:
        return failure("not_found", "Parceiro não encontrado.", status=404)
    body = body_json()
    slug = normalized_slug(str(body.get("slug", row.slug)))
    if not slug or db.session.scalar(
        select(Partner.id).where(Partner.slug == slug, Partner.id != row.id)
    ):
        return failure("conflict", "Já existe um parceiro com este slug.", status=409)
    if "name" in body and str(body["name"]).strip():
        row.name = str(body["name"]).strip()[:140]
    row.slug = slug
    for field, limit in (("logo_path", 500), ("logo_alt", 180), ("category", 60), ("level", 60)):
        if field in body:
            setattr(row, field, str(body[field]).strip()[:limit] or None)
    if "website_url" in body:
        row.website_url = safe_http_url(str(body["website_url"]))
    if "active" in body:
        row.active = bool(body["active"])
    audit("partner.updated", "partner", "Parceiro atualizado", str(row.id))
    db.session.commit()
    return success({"id": str(row.id), "slug": row.slug, "active": row.active})


@bp.delete("/admin/partners/<partner_id>")
@require_permission("partners.manage")
def partner_delete(partner_id: str):
    row = db.session.get(Partner, parse_uuid(partner_id)) if parse_uuid(partner_id) else None
    if not row or row.deleted_at:
        return failure("not_found", "Parceiro não encontrado.", status=404)
    row.active = False
    row.deleted_at = datetime.now(UTC)
    audit("partner.archived", "partner", "Parceiro arquivado", str(row.id))
    db.session.commit()
    return success({"id": str(row.id), "active": row.active})


@bp.post("/admin/content/<key>/publish")
@require_permission("content.manage")
def content_publish(key: str):
    body = body_json()
    entry = db.session.scalar(select(ContentEntry).where(ContentEntry.key == key))
    if not entry:
        entry = ContentEntry(
            key=key[:140], title=str(body.get("title", key))[:180], content_type="json"
        )
        db.session.add(entry)
        db.session.flush()
    latest = (
        db.session.scalar(
            select(ContentVersion.version)
            .where(ContentVersion.entry_id == entry.id)
            .order_by(ContentVersion.version.desc())
            .limit(1)
        )
        or 0
    )
    version = ContentVersion(
        entry_id=entry.id,
        version=latest + 1,
        value_json=json.dumps(body.get("value", {}), ensure_ascii=False),
        status="published",
        created_by_id=g.current_user.id,
        published_at=datetime.now(UTC),
    )
    db.session.add(version)
    db.session.flush()
    entry.current_version_id = version.id
    audit("content.published", "content_entry", "Nova versão publicada", str(entry.id))
    db.session.commit()
    return success({"id": str(entry.id), "version": version.version})


@bp.get("/admin/content")
@require_permission("content.manage")
def content_list():
    rows = db.session.scalars(select(ContentEntry).order_by(ContentEntry.key).limit(200)).all()
    return success(
        [
            {
                "id": str(row.id),
                "key": row.key,
                "title": row.title,
                "content_type": row.content_type,
            }
            for row in rows
        ]
    )


@bp.delete("/admin/content/<key>")
@require_permission("content.manage")
def content_archive(key: str):
    entry = db.session.scalar(select(ContentEntry).where(ContentEntry.key == key))
    if not entry:
        return failure("not_found", "Conteúdo não encontrado.", status=404)
    versions = db.session.scalars(
        select(ContentVersion).where(ContentVersion.entry_id == entry.id)
    ).all()
    for version in versions:
        version.status = "archived"
    entry.current_version_id = None
    audit("content.archived", "content_entry", "Conteúdo arquivado", str(entry.id))
    db.session.commit()
    return success({"id": str(entry.id), "status": "archived"})


@bp.patch("/admin/gallery/order")
@require_permission("gallery.manage")
def gallery_order():
    album_id = parse_uuid(body_json().get("album_id"))
    ids = body_json().get("ids", [])
    if not album_id or not isinstance(ids, list) or len(ids) > 200:
        return failure("validation_error", "Ordem inválida.", status=422)
    parsed_ids = [parse_uuid(raw) for raw in ids]
    if any(parsed is None for parsed in parsed_ids) or len(set(parsed_ids)) != len(parsed_ids):
        return failure(
            "validation_error", "A ordem contém IDs inválidos ou duplicados.", status=422
        )
    rows = db.session.scalars(
        select(GalleryMedia).where(
            GalleryMedia.id.in_(parsed_ids),
            GalleryMedia.album_id == album_id,
            GalleryMedia.deleted_at.is_(None),
        )
    ).all()
    if len(rows) != len(parsed_ids):
        return failure("validation_error", "A ordem contém mídia de outro álbum.", status=422)
    by_id = {row.id: row for row in rows}
    for order, raw in enumerate(ids):
        by_id[parse_uuid(raw)].display_order = order
    audit("gallery.reordered", "gallery_media", "Ordem da galeria salva")
    db.session.commit()
    return success({"saved": True})


def cipher() -> Fernet | None:
    key = current_app.config["MEDIA_TOKEN_ENCRYPTION_KEY"]
    try:
        return Fernet(key.encode()) if key else None
    except (ValueError, TypeError):
        return None


@bp.get("/admin/integrations/google-drive/authorize")
@require_permission("system.read")
def google_authorize():
    if (
        not current_app.config["GOOGLE_CLIENT_ID"]
        or not current_app.config["GOOGLE_REDIRECT_URI"]
        or not cipher()
    ):
        return failure("integration_disabled", "Google Drive não está configurado.", status=409)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    row = OAuthState(
        state_hash=sha256(state),
        encrypted_verifier=cipher().encrypt(verifier.encode()),
        user_id=g.current_user.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.session.add(row)
    db.session.commit()
    query = urlencode(
        {
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.file",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@bp.get("/admin/integrations/google-drive/callback")
def google_callback():
    if not g.current_user or not cipher():
        return failure("authentication_required", "Autenticação necessária.", status=401)
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    row = db.session.scalar(
        select(OAuthState).where(
            OAuthState.state_hash == sha256(state), OAuthState.consumed_at.is_(None)
        )
    )
    if (
        not row
        or row.user_id != g.current_user.id
        or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or UTC) <= datetime.now(UTC)
    ):
        return failure("oauth_state_invalid", "Autorização expirada ou inválida.", status=400)
    try:
        verifier = cipher().decrypt(row.encrypted_verifier).decode()
    except InvalidToken:
        return failure("oauth_state_invalid", "Autorização inválida.", status=400)
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        timeout=15,
        data={
            "client_id": current_app.config["GOOGLE_CLIENT_ID"],
            "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
        },
    )
    if not response.ok:
        return failure("oauth_exchange_failed", "O Google não concluiu a autorização.", status=502)
    tokens = response.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        return failure(
            "oauth_refresh_missing", "O Google não forneceu acesso duradouro.", status=409
        )
    credential = db.session.scalar(
        select(IntegrationCredential).where(IntegrationCredential.provider == "google_drive")
    )
    encrypted = cipher().encrypt(json.dumps({"refresh_token": refresh}).encode())
    if credential:
        credential.encrypted_payload = encrypted
        credential.key_version = "v1"
        credential.status = "active"
    else:
        db.session.add(
            IntegrationCredential(
                provider="google_drive",
                encrypted_payload=encrypted,
                key_version="v1",
                scopes_json='["drive.file"]',
            )
        )
    row.consumed_at = datetime.now(UTC)
    audit("integration.connected", "integration", "Google Drive conectado")
    db.session.commit()
    return redirect(f"{current_app.config['PUBLIC_BASE_URL']}/painel/sistema?drive=connected")
