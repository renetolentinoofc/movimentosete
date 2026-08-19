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

from ..extensions import db
from ..http import failure, success
from ..models import (
    ContentEntry,
    ContentVersion,
    EventEdition,
    GalleryAlbum,
    GalleryMedia,
    IntegrationCredential,
    OAuthState,
    Partner,
    Product,
    ProductMedia,
    ProductVariant,
    Registration,
)
from ..security import audit, require_permission, sha256
from ..services.media import GoogleDriveMediaProvider, LocalMediaProvider, process_portfolio_image
from ..validation import aware_utc, parse_uuid, safe_http_url

bp = Blueprint("admin_ops", __name__)


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


def body_json() -> dict:
    return request.get_json(silent=True) or {}


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
                "price_cents": row.price_cents,
                "status": row.status,
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


@bp.get("/admin/partners")
@require_permission("partners.manage")
def partners_list():
    rows = db.session.scalars(select(Partner).order_by(Partner.display_order).limit(100)).all()
    return success(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "slug": row.slug,
                "active": row.active,
                "category": row.category,
                "level": row.level,
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


@bp.patch("/admin/gallery/order")
@require_permission("gallery.manage")
def gallery_order():
    ids = body_json().get("ids", [])
    if not isinstance(ids, list) or len(ids) > 200:
        return failure("validation_error", "Ordem inválida.", status=422)
    for order, raw in enumerate(ids):
        parsed = parse_uuid(raw)
        row = db.session.get(GalleryMedia, parsed) if parsed else None
        if row:
            row.display_order = order
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
    return redirect(
        f"{current_app.config['PUBLIC_BASE_URL']}/painel/sistema?drive=connected"
    )
