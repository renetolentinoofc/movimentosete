import io
import json
import secrets
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from flask import Blueprint, current_app, request, send_file
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_, select
from werkzeug.utils import secure_filename

from ..extensions import db
from ..http import failure, success
from ..models import (
    ContactMessage,
    ContentEntry,
    ContentVersion,
    EventEdition,
    GalleryAlbum,
    GalleryMedia,
    ParticipationCategory,
    Partner,
    PortfolioAsset,
    Profile,
    ProfileCategory,
    Registration,
    RegistrationFile,
    RegistrationStatusHistory,
    SiteSetting,
    SocialLink,
)
from ..security import rate_limited, sha256
from ..services.communications import dispatch_email
from ..services.email_delivery import valid_email
from ..services.email_templates import contact_message_received, registration_confirmation
from ..services.media import LocalMediaProvider
from ..validation import aware_utc, normalize_instagram, normalize_phone, safe_http_url

bp = Blueprint("public", __name__)


def protocol(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m}-{secrets.token_hex(4).upper()}"


def page_args() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", "1")))
        limit = min(50, max(1, int(request.args.get("limit", "12"))))
    except ValueError:
        page, limit = 1, 12
    return page, limit


@bp.get("/site")
def site():
    entries = db.session.scalars(
        select(ContentEntry).where(ContentEntry.current_version_id.is_not(None))
    ).all()
    content: dict[str, object] = {}
    for entry in entries:
        version = db.session.get(ContentVersion, entry.current_version_id)
        if version and version.status == "published":
            content[entry.key] = json.loads(version.value_json)
    settings = {
        item.key: json.loads(item.value_json)
        for item in db.session.scalars(
            select(SiteSetting).where(SiteSetting.public.is_(True))
        ).all()
    }
    socials = [
        {"network": link.network, "label": link.label, "url": link.url}
        for link in db.session.scalars(
            select(SocialLink).where(SocialLink.active.is_(True)).order_by(SocialLink.display_order)
        ).all()
    ]
    return success({"content": content, "settings": settings, "social_links": socials})


@bp.get("/editions/current")
def current_edition():
    edition = db.session.scalar(
        select(EventEdition)
        .where(EventEdition.status == "published")
        .order_by(EventEdition.starts_at.asc().nullslast())
        .limit(1)
    )
    if not edition:
        return success(None)
    now = datetime.now(UTC)
    count = db.session.scalar(
        select(func.count())
        .select_from(Registration)
        .where(Registration.edition_id == edition.id, Registration.deleted_at.is_(None))
    )
    registrations_open = bool(
        edition.registration_opens_at
        and edition.registration_closes_at
        and aware_utc(edition.registration_opens_at)
        <= now
        <= aware_utc(edition.registration_closes_at)
        and (edition.capacity is None or int(count or 0) < edition.capacity)
    )
    return success(
        {
            "id": str(edition.id),
            "name": edition.name,
            "slug": edition.slug,
            "description": edition.description,
            "starts_at": edition.starts_at,
            "ends_at": edition.ends_at,
            "location": edition.location,
            "address": edition.address,
            "map_url": edition.map_url,
            "registrations_open": registrations_open,
        }
    )


@bp.get("/categories")
def categories():
    rows = db.session.scalars(
        select(ParticipationCategory)
        .where(ParticipationCategory.active.is_(True))
        .order_by(ParticipationCategory.display_order, ParticipationCategory.name)
    ).all()
    return success(
        [
            {
                "id": str(row.id),
                "name": row.name,
                "slug": row.slug,
                "description": row.description,
                "accepts_file": row.accepts_file,
                "accepts_link": row.accepts_link,
                "extra_fields": json.loads(row.extra_fields_json),
            }
            for row in rows
        ]
    )


@bp.post("/registrations")
def create_registration():
    if rate_limited("registration", 8, 3600):
        db.session.rollback()
        return failure("rate_limited", "Muitas tentativas. Tente novamente mais tarde.", status=429)
    body = request.get_json(silent=True) or {}
    if body.get("website") or body.get("fax_number_for_bots"):
        return success({"protocol": protocol("M7")}, status=201)
    required = {
        "full_name": "Informe seu nome.",
        "email": "Informe seu e-mail.",
        "phone": "Informe seu WhatsApp.",
        "city": "Informe sua cidade.",
        "category": "Escolha uma categoria.",
        "presentation": "Faça uma breve apresentação.",
        "privacy_version": "Aceite a política de privacidade.",
    }
    fields = {
        key: [message] for key, message in required.items() if not str(body.get(key, "")).strip()
    }
    if body.get("privacy_accepted") is not True:
        fields["privacy_accepted"] = ["O aceite é necessário para enviar a inscrição."]
    email = str(body.get("email", "")).strip().lower()
    if email and not valid_email(email):
        fields["email"] = ["Informe um e-mail válido."]
    phone = normalize_phone(str(body.get("phone", "")))
    if not phone:
        fields["phone"] = ["Use um WhatsApp brasileiro válido com DDD."]
    instagram = normalize_instagram(str(body.get("instagram", "")))
    if body.get("instagram") and not instagram:
        fields["instagram"] = ["Use apenas o nome de usuário do Instagram."]
    portfolio_url = safe_http_url(str(body.get("portfolio_url", "")))
    if body.get("portfolio_url") and not portfolio_url:
        fields["portfolio_url"] = ["Use um endereço http:// ou https:// válido."]
    category = db.session.scalar(
        select(ParticipationCategory).where(
            ParticipationCategory.slug == str(body.get("category", "")),
            ParticipationCategory.active.is_(True),
        )
    )
    if not category:
        fields["category"] = ["Categoria indisponível."]
    now = datetime.now(UTC)
    edition = db.session.scalar(
        select(EventEdition)
        .where(
            EventEdition.status == "published",
            EventEdition.registration_opens_at <= now,
            EventEdition.registration_closes_at >= now,
        )
        .order_by(EventEdition.starts_at)
        .with_for_update()
        .limit(1)
    )
    if not edition:
        fields["edition"] = ["As inscrições desta edição não estão abertas."]
    elif edition.capacity is not None:
        current_count = db.session.scalar(
            select(func.count())
            .select_from(Registration)
            .where(Registration.edition_id == edition.id, Registration.deleted_at.is_(None))
        )
        if int(current_count or 0) >= edition.capacity:
            fields["edition"] = ["As vagas desta edição foram preenchidas."]
    if len(str(body.get("presentation", ""))) > 3000:
        fields["presentation"] = ["Use no máximo 3.000 caracteres."]
    if fields:
        db.session.rollback()
        return failure(
            "validation_error", "Revise os campos informados.", status=422, fields=fields
        )
    upload_token = secrets.token_urlsafe(32)
    registration = Registration(
        protocol=protocol("M7"),
        upload_token_hash=sha256(upload_token),
        edition_id=edition.id if edition else None,
        category_id=category.id,
        full_name=str(body["full_name"]).strip(),
        professional_name=str(body.get("professional_name", "")).strip() or None,
        email=email,
        phone_e164=phone,
        instagram_handle=instagram,
        city=str(body["city"]).strip(),
        presentation=str(body["presentation"]).strip(),
        portfolio_url=portfolio_url,
        extra_data_json=json.dumps(body.get("extra_data", {}), ensure_ascii=False),
        consent_at=now,
        privacy_version=str(body["privacy_version"]).strip(),
        consent_purpose="inscrição e processo de seleção",
    )
    db.session.add(registration)
    db.session.flush()
    db.session.add(
        RegistrationStatusHistory(
            registration_id=registration.id,
            old_status=None,
            new_status="received",
            reason="Inscrição enviada pela pessoa participante",
            created_at=now,
        )
    )
    db.session.commit()
    notification = dispatch_email(
        recipient=email,
        template=registration_confirmation(
            name=registration.full_name,
            protocol=registration.protocol,
            category=category.name,
        ),
        idempotency_key=f"registration:{registration.id}:received",
        registration_id=registration.id,
    )
    db.session.commit()
    return success(
        {
            "protocol": registration.protocol,
            "category": category.name,
            "professional_name": registration.professional_name,
            "upload_token": upload_token,
            "notification_status": notification.status,
        },
        status=201,
    )


@bp.post("/registrations/<registration_protocol>/files")
def upload_registration_file(registration_protocol: str):
    if rate_limited("registration-upload", 12, 3600):
        db.session.rollback()
        return failure("rate_limited", "Muitos uploads. Tente novamente mais tarde.", status=429)
    token = request.headers.get("X-Upload-Token", "")
    registration = db.session.scalar(
        select(Registration).where(Registration.protocol == registration_protocol)
    )
    if not registration or not token or registration.upload_token_hash != sha256(token):
        return failure("not_found", "Inscrição não encontrada.", status=404)
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return failure(
            "validation_error",
            "Selecione um arquivo.",
            status=422,
            fields={"file": ["Arquivo obrigatório."]},
        )
    content = uploaded.read()
    if not content or len(content) > 10 * 1024 * 1024:
        return failure(
            "validation_error",
            "Arquivo inválido.",
            status=422,
            fields={"file": ["O arquivo deve ter até 10 MB."]},
        )
    allowed = {
        "JPEG": ("image/jpeg", ".jpg"),
        "PNG": ("image/png", ".png"),
        "WEBP": ("image/webp", ".webp"),
    }
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
            detected = allowed.get(image.format or "")
    except (UnidentifiedImageError, OSError):
        detected = None
        width = height = None
    if not detected:
        return failure(
            "validation_error",
            "Formato não permitido.",
            status=422,
            fields={"file": ["Envie JPG, PNG ou WebP válido."]},
        )
    provider = LocalMediaProvider(Path("instance/uploads/registrations"))
    stored = provider.store(content, detected[1], detected[0])
    row = RegistrationFile(
        registration_id=registration.id,
        provider=stored.provider,
        storage_key=stored.storage_key,
        original_name=secure_filename(uploaded.filename)[:255] or "portfolio",
        safe_name=stored.storage_key,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        width=width,
        height=height,
        sha256=stored.sha256,
    )
    try:
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        provider.delete(stored.storage_key)
        raise
    return success({"id": str(row.id), "status": row.processing_status}, status=201)


@bp.get("/profiles")
def profiles():
    page, limit = page_args()
    query = select(Profile).where(Profile.status == "published")
    search = request.args.get("q", "").strip()[:80]
    city = request.args.get("city", "").strip()[:120]
    category = request.args.get("category", "").strip()[:100]
    if search:
        query = query.where(
            or_(Profile.display_name.ilike(f"%{search}%"), Profile.city.ilike(f"%{search}%"))
        )
    if city:
        query = query.where(Profile.city.ilike(f"%{city}%"))
    if category:
        query = (
            query.join(ProfileCategory, ProfileCategory.profile_id == Profile.id)
            .join(
                ParticipationCategory,
                ParticipationCategory.id == ProfileCategory.category_id,
            )
            .where(ParticipationCategory.slug == category)
        )
    rows = db.session.scalars(
        query.distinct()
        .order_by(Profile.featured.desc(), Profile.published_at.desc())
        .offset((page - 1) * limit)
        .limit(limit + 1)
    ).all()
    data = []
    for row in rows[:limit]:
        categories = db.session.scalars(
            select(ParticipationCategory)
            .join(ProfileCategory, ProfileCategory.category_id == ParticipationCategory.id)
            .where(ProfileCategory.profile_id == row.id)
            .order_by(ParticipationCategory.display_order, ParticipationCategory.name)
        ).all()
        cover = db.session.scalar(
            select(PortfolioAsset)
            .where(PortfolioAsset.profile_id == row.id, PortfolioAsset.active.is_(True))
            .order_by(PortfolioAsset.display_order, PortfolioAsset.created_at)
            .limit(1)
        )
        data.append(
            {
                "slug": row.slug,
                "display_name": row.display_name,
                "bio": row.bio,
                "city": row.city,
                "instagram": row.instagram_handle,
                "featured": row.featured,
                "categories": [item.name for item in categories],
                "category_slugs": [item.slug for item in categories],
                "cover": (
                    {
                        "url": f"/api/v1/profile-assets/{cover.id}/file",
                        "type": cover.media_type,
                        "alt": cover.alt_text,
                        "credit": cover.credit,
                    }
                    if cover
                    else None
                ),
            }
        )
    return success(
        data,
        meta={"page": page, "limit": limit, "has_more": len(rows) > limit},
    )


@bp.get("/profiles/<slug>")
def profile_detail(slug: str):
    row = db.session.scalar(
        select(Profile).where(Profile.slug == slug, Profile.status == "published")
    )
    if not row:
        return failure("not_found", "Perfil não encontrado.", status=404)
    categories = db.session.scalars(
        select(ParticipationCategory)
        .join(ProfileCategory, ProfileCategory.category_id == ParticipationCategory.id)
        .where(ProfileCategory.profile_id == row.id)
    ).all()
    assets = db.session.scalars(
        select(PortfolioAsset)
        .where(PortfolioAsset.profile_id == row.id, PortfolioAsset.active.is_(True))
        .order_by(PortfolioAsset.display_order)
        .limit(30)
    ).all()
    return success(
        {
            "slug": row.slug,
            "display_name": row.display_name,
            "bio": row.bio,
            "city": row.city,
            "instagram": row.instagram_handle,
            "featured": row.featured,
            "published_at": row.published_at,
            "categories": [c.name for c in categories],
            "portfolio": [
                {
                    "id": str(a.id),
                    "url": f"/api/v1/profile-assets/{a.id}/file",
                    "type": a.media_type,
                    "alt": a.alt_text,
                    "credit": a.credit,
                }
                for a in assets
            ],
        }
    )


@bp.get("/profile-assets/<asset_id>/file")
def public_profile_asset_file(asset_id: str):
    try:
        parsed = UUID(asset_id)
    except ValueError:
        return failure("not_found", "Mídia não encontrada.", status=404)
    item = db.session.scalar(
        select(PortfolioAsset)
        .join(Profile, Profile.id == PortfolioAsset.profile_id)
        .where(
            PortfolioAsset.id == parsed,
            PortfolioAsset.active.is_(True),
            Profile.status == "published",
        )
    )
    if not item:
        return failure("not_found", "Mídia não encontrada.", status=404)
    if item.provider != "local":
        return failure(
            "provider_unavailable",
            "Esta mídia está temporariamente indisponível.",
            status=409,
        )
    root = Path("instance/uploads/registrations").resolve()
    target = (root / item.storage_key).resolve()
    if root not in target.parents or not target.is_file():
        return failure("not_found", "Mídia não encontrada.", status=404)
    return send_file(target, as_attachment=False, conditional=True)


@bp.get("/gallery")
def gallery():
    page, limit = page_args()
    query = (
        select(GalleryMedia, GalleryAlbum)
        .join(GalleryAlbum)
        .where(
            GalleryMedia.status == "published",
            GalleryMedia.deleted_at.is_(None),
            GalleryAlbum.status == "published",
        )
    )
    if request.args.get("category"):
        query = query.where(GalleryMedia.category == request.args["category"])
    rows = db.session.execute(
        query.order_by(GalleryMedia.display_order).offset((page - 1) * limit).limit(limit + 1)
    ).all()
    return success(
        [
            {
                "id": str(media.id),
                "album": album.title,
                "edition": album.slug,
                "category": media.category,
                "type": media.media_type,
                "url": media.storage_key,
                "title": media.title,
                "caption": media.caption,
                "alt": media.alt_text,
                "credit": media.credit,
                "width": media.width,
                "height": media.height,
            }
            for media, album in rows[:limit]
        ],
        meta={"page": page, "limit": limit, "has_more": len(rows) > limit},
    )


@bp.get("/partners")
def partners():
    today = date.today()
    rows = db.session.scalars(
        select(Partner)
        .where(Partner.active.is_(True), Partner.deleted_at.is_(None))
        .order_by(Partner.display_order)
    ).all()
    rows = [
        row
        for row in rows
        if (not row.starts_on or row.starts_on <= today)
        and (not row.ends_on or row.ends_on >= today)
    ]
    return success(
        [
            {
                "name": row.name,
                "slug": row.slug,
                "description": row.description,
                "website_url": row.website_url,
                "logo_path": row.logo_path,
                "logo_alt": row.logo_alt,
                "category": row.category,
                "level": row.level,
            }
            for row in rows
        ]
    )


@bp.post("/contact")
def contact():
    if rate_limited("contact", 5, 3600):
        db.session.rollback()
        return failure("rate_limited", "Muitas tentativas. Tente novamente mais tarde.", status=429)
    body = request.get_json(silent=True) or {}
    if body.get("website") or body.get("fax_number_for_bots"):
        return success({"protocol": protocol("CT")}, status=201)
    required = ("name", "email", "subject", "message", "privacy_version")
    fields = {
        field: ["Campo obrigatório."] for field in required if not str(body.get(field, "")).strip()
    }
    if body.get("privacy_accepted") is not True:
        fields["privacy_accepted"] = ["O aceite é necessário."]
    email = str(body.get("email", "")).strip().lower()
    if email and not valid_email(email):
        fields["email"] = ["Informe um e-mail válido."]
    if len(str(body.get("name", "")).strip()) > 140:
        fields["name"] = ["Use no máximo 140 caracteres."]
    if len(str(body.get("subject", "")).strip()) > 140:
        fields["subject"] = ["Use no máximo 140 caracteres."]
    if len(str(body.get("message", "")).strip()) > 5000:
        fields["message"] = ["Use no máximo 5.000 caracteres."]
    if fields:
        db.session.rollback()
        return failure(
            "validation_error", "Revise os campos informados.", status=422, fields=fields
        )
    row = ContactMessage(
        protocol=protocol("CT"),
        name=str(body["name"]).strip(),
        email=email,
        phone_e164=normalize_phone(str(body.get("phone", ""))),
        subject=str(body["subject"]).strip(),
        message=str(body["message"]).strip(),
        consent_at=datetime.now(UTC),
        privacy_version=str(body["privacy_version"]),
    )
    db.session.add(row)
    db.session.commit()
    notification_status = "unavailable"
    contact_recipient = str(current_app.config["EMAIL_CONTACT_RECIPIENT"])
    if valid_email(contact_recipient):
        notification = dispatch_email(
            recipient=contact_recipient,
            template=contact_message_received(
                name=row.name,
                email=row.email,
                subject=row.subject,
                message=row.message,
                protocol=row.protocol,
            ),
            idempotency_key=f"contact:{row.id}:team",
            contact_id=row.id,
            reply_to=row.email,
        )
        notification_status = notification.status
        db.session.commit()
    return success(
        {"protocol": row.protocol, "notification_status": notification_status}, status=201
    )
