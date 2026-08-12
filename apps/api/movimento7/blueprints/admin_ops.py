import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, current_app, g, redirect, request
from sqlalchemy import select

from ..extensions import db
from ..http import failure, success
from ..models import (
    ContentEntry,
    ContentVersion,
    EventEdition,
    GalleryMedia,
    IntegrationCredential,
    OAuthState,
    Partner,
    Product,
    ProductVariant,
)
from ..security import audit, require_permission, sha256
from ..validation import parse_uuid, safe_http_url

bp = Blueprint("admin_ops", __name__)


def body_json() -> dict:
    return request.get_json(silent=True) or {}


@bp.get("/admin/editions")
@require_permission("events.manage")
def editions_list():
    rows = db.session.scalars(
        select(EventEdition).order_by(EventEdition.created_at.desc()).limit(100)
    ).all()
    return success(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "slug": row.slug,
                "status": row.status,
                "starts_at": row.starts_at,
                "registration_opens_at": row.registration_opens_at,
                "registration_closes_at": row.registration_closes_at,
            }
            for row in rows
        ]
    )


@bp.post("/admin/editions")
@require_permission("events.manage")
def editions_create():
    body = body_json()
    if not body.get("name") or not body.get("slug"):
        return failure("validation_error", "Nome e slug são obrigatórios.", status=422)
    if db.session.scalar(select(EventEdition).where(EventEdition.slug == body["slug"])):
        return failure("conflict", "Já existe uma edição com este slug.", status=409)
    row = EventEdition(
        name=str(body["name"])[:140],
        slug=str(body["slug"])[:160],
        description=str(body.get("description", "")) or None,
        status=str(body.get("status", "draft")),
    )
    db.session.add(row)
    audit("edition.created", "event_edition", "Edição criada", str(row.id))
    db.session.commit()
    return success({"id": str(row.id)}, status=201)


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
    return redirect("/admin/sistema?drive=connected")
