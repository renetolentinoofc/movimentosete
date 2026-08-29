import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from flask import Blueprint, current_app, request
from sqlalchemy import select

from ..extensions import db
from ..http import failure, success
from ..models import Artwork, ArtworkMedia, AuctionAuthorization, AuctionLot, Bid, Bidder
from ..security import rate_limited
from ..services.email_delivery import valid_email
from ..services.payments import MercadoPagoError, MercadoPagoProvider
from ..validation import aware_utc, normalize_phone, parse_uuid

bp = Blueprint("auctions", __name__)


def lot_json(lot: AuctionLot, artwork: Artwork, detail: bool = False) -> dict:
    media = db.session.scalars(
        select(ArtworkMedia)
        .where(ArtworkMedia.artwork_id == artwork.id)
        .order_by(ArtworkMedia.display_order)
        .limit(20)
    ).all()
    data = {
        "id": str(lot.id),
        "slug": lot.slug,
        "title": lot.title,
        "artist_name": artwork.artist_name,
        "technique": artwork.technique,
        "dimensions": artwork.dimensions,
        "starting_bid_cents": lot.starting_bid_cents,
        "current_bid_cents": lot.current_bid_cents,
        "minimum_increment_cents": lot.minimum_increment_cents,
        "opens_at": lot.opens_at,
        "closes_at": lot.closes_at,
        "status": lot.status,
        "bidding_enabled": bool(current_app.config["AUCTION_BIDDING_ENABLED"]),
        "terms_version": current_app.config["AUCTION_TERMS_VERSION"],
        "media": [
            {"url": item.storage_key, "alt": item.alt_text, "credit": item.credit} for item in media
        ],
    }
    if detail:
        data["description"] = artwork.description
        data["rules"] = lot.rules
        bids = db.session.scalars(
            select(Bid)
            .where(Bid.lot_id == lot.id, Bid.status == "valid")
            .order_by(Bid.amount_cents.desc(), Bid.created_at.desc())
            .limit(50)
        ).all()
        aliases = (
            {
                row.id: row.display_alias
                for row in db.session.scalars(
                    select(Bidder).where(Bidder.id.in_({b.bidder_id for b in bids}))
                ).all()
            }
            if bids
            else {}
        )
        data["bid_history"] = [
            {
                "alias": aliases.get(b.bidder_id, "Participante"),
                "amount_cents": b.amount_cents,
                "created_at": b.created_at,
            }
            for b in bids
        ]
    return data


@bp.get("/auction-lots")
def lots():
    rows = db.session.execute(
        select(AuctionLot, Artwork)
        .join(Artwork)
        .where(AuctionLot.status.in_(("published", "open", "closed")))
        .order_by(AuctionLot.closes_at)
        .limit(100)
    ).all()
    return success([lot_json(lot, artwork) for lot, artwork in rows])


@bp.get("/auction-lots/<slug>")
def lot_detail(slug: str):
    row = db.session.execute(
        select(AuctionLot, Artwork)
        .join(Artwork)
        .where(AuctionLot.slug == slug, AuctionLot.status.in_(("published", "open", "closed")))
    ).first()
    if not row:
        return failure("not_found", "Lote não encontrado.", status=404)
    return success(lot_json(row[0], row[1], detail=True))


@bp.post("/auction-lots/<lot_id>/authorizations")
def authorize_auction_bid(lot_id: str):
    if not current_app.config["AUCTION_BIDDING_ENABLED"]:
        return failure(
            "bidding_disabled", "Os lances ainda não estão habilitados.", status=409
        )
    if not current_app.config["AUCTION_PAYMENT_GUARANTEE_ENABLED"]:
        return failure(
            "bidding_payment_not_ready",
            "A garantia de pagamento ainda não está disponível.",
            status=503,
        )
    if current_app.config["PAYMENT_PROVIDER"] != "mercadopago":
        return failure("auction_payment_unavailable", "O leilão exige Mercado Pago.", status=503)
    idempotency = request.headers.get("Idempotency-Key", "").strip()
    if not 8 <= len(idempotency) <= 100:
        return failure(
            "idempotency_required", "Informe uma chave de idempotência válida.", status=400
        )
    body = request.get_json(silent=True) or {}
    request_hash = sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    existing = db.session.scalar(
        select(AuctionAuthorization).where(AuctionAuthorization.idempotency_key == idempotency)
    )
    if existing:
        if existing.request_hash != request_hash:
            return failure(
                "idempotency_conflict",
                "A chave de idempotência já foi usada com outro pagamento.",
                status=409,
            )
        return success({"id": str(existing.id), "status": existing.status, "replayed": True})
    parsed_lot_id = parse_uuid(lot_id)
    lot = db.session.scalar(
        select(AuctionLot).where(AuctionLot.id == parsed_lot_id).with_for_update()
    ) if parsed_lot_id else None
    now = datetime.now(UTC)
    try:
        amount = int(body.get("amount_cents", 0))
        installments = int(body.get("installments", 1))
    except (TypeError, ValueError):
        amount = installments = 0
    email = str(body.get("email", "")).strip().lower()
    phone = normalize_phone(str(body.get("phone", "")))
    fields = {}
    if not lot or lot.status != "open" or not lot.closes_at or not aware_utc(lot.closes_at) > now:
        return failure("lot_not_open", "Este lote não está aberto para lances.", status=409)
    minimum = (
        lot.starting_bid_cents
        if lot.current_bid_cents is None
        else lot.current_bid_cents + lot.minimum_increment_cents
    )
    if amount < minimum:
        fields["amount_cents"] = [f"O valor mínimo é {minimum} centavos."]
    if not valid_email(email):
        fields["email"] = ["Informe um e-mail válido."]
    if len(str(body.get("name", "")).strip()) < 2:
        fields["name"] = ["Informe seu nome."]
    if not phone:
        fields["phone"] = ["WhatsApp inválido."]
    if not 1 <= installments <= 12:
        fields["installments"] = ["Informe entre 1 e 12 parcelas."]
    if body.get("terms_accepted") is not True:
        fields["terms_accepted"] = ["Aceite as regras do leilão."]
    if str(body.get("terms_version", "")).strip() != current_app.config["AUCTION_TERMS_VERSION"]:
        fields["terms_version"] = ["Aceite a versão vigente das regras do leilão."]
    if (
        not str(body.get("card_token", "")).strip()
        or not str(body.get("payment_method_id", "")).strip()
    ):
        fields["payment"] = ["Dados do cartão não foram tokenizados."]
    if fields:
        db.session.rollback()
        return failure("validation_error", "Revise os dados informados.", status=422, fields=fields)
    bidder = Bidder(
        display_alias=f"Participante {str(lot.id)[-4:].upper()}",
        name=str(body.get("name", "")).strip(), email=email, phone_e164=phone,
    )
    db.session.add(bidder)
    db.session.flush()
    try:
        result = MercadoPagoProvider().authorize_auction(
            external_reference=f"auction:{lot.id}:{idempotency}", amount_cents=amount,
            payer_email=email, card_token=str(body["card_token"]).strip(),
            payment_method_id=str(body["payment_method_id"]).strip(),
            installments=installments, idempotency_key=idempotency,
        )
    except MercadoPagoError as error:
        db.session.rollback()
        return failure("auction_payment_failed", str(error), status=502)
    if result.status != "authorized" or not result.provider_reference:
        db.session.rollback()
        return failure(
            "auction_payment_not_authorized",
            "O cartão não foi autorizado para garantia.",
            status=402,
        )
    authorization = AuctionAuthorization(
        lot_id=lot.id, bidder_id=bidder.id, provider="mercadopago",
        provider_order_id=result.provider_reference,
        provider_payment_id=(result.metadata or {}).get("payment_id"), amount_cents=amount,
        status="authorized", idempotency_key=idempotency, expires_at=now + timedelta(days=5),
        request_hash=request_hash,
    )
    db.session.add(authorization)
    db.session.commit()
    return success({"id": str(authorization.id), "status": authorization.status,
                    "amount_cents": amount, "expires_at": authorization.expires_at}, status=201)


@bp.post("/auction-lots/<lot_id>/bids")
def create_bid(lot_id: str):
    if not current_app.config["AUCTION_BIDDING_ENABLED"]:
        return failure(
            "bidding_disabled",
            "Os lotes estão em modo de exposição. Lances ainda não estão habilitados.",
            status=409,
        )
    if not current_app.config["AUCTION_PAYMENT_GUARANTEE_ENABLED"]:
        return failure(
            "bidding_payment_not_ready",
            "A garantia de pagamento ainda não está disponível para este leilão.",
            status=503,
        )
    if rate_limited("bid", 20, 300):
        db.session.rollback()
        return failure("rate_limited", "Muitas tentativas de lance.", status=429)
    idempotency = request.headers.get("Idempotency-Key", "").strip()
    if not 8 <= len(idempotency) <= 100:
        return failure(
            "idempotency_required", "Informe uma chave de idempotência válida.", status=400
        )
    existing = db.session.scalar(select(Bid).where(Bid.idempotency_key == idempotency))
    body = request.get_json(silent=True) or {}
    authorization_id = parse_uuid(body.get("authorization_id"))
    request_hash = sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if existing:
        if existing.request_hash and existing.request_hash != request_hash:
            return failure(
                "idempotency_conflict",
                "A chave de idempotência já foi usada com outro lance.",
                status=409,
            )
        return success(
            {
                "id": str(existing.id),
                "amount_cents": existing.amount_cents,
                "created_at": existing.created_at,
                "replayed": True,
            }
        )
    try:
        amount = int(body.get("amount_cents", 0))
    except (TypeError, ValueError):
        amount = 0
    phone = normalize_phone(str(body.get("phone", "")))
    fields = {}
    for key in ("name", "email"):
        if not str(body.get(key, "")).strip():
            fields[key] = ["Campo obrigatório."]
    if body.get("email") and not valid_email(str(body["email"]).strip()):
        fields["email"] = ["Informe um e-mail válido."]
    if not phone:
        fields["phone"] = ["WhatsApp inválido."]
    if body.get("terms_accepted") is not True:
        fields["terms_accepted"] = ["Aceite as regras do leilão."]
    if str(body.get("terms_version", "")).strip() != current_app.config["AUCTION_TERMS_VERSION"]:
        fields["terms_version"] = ["Aceite a versão vigente das regras do leilão."]
    if fields:
        return failure(
            "validation_error", "Revise os campos informados.", status=422, fields=fields
        )
    try:
        parsed_lot_id = parse_uuid(lot_id)
        lot = (
            db.session.scalar(
                select(AuctionLot).where(AuctionLot.id == parsed_lot_id).with_for_update()
            )
            if parsed_lot_id
            else None
        )
        now = datetime.now(UTC)
        if (
            not lot
            or lot.status != "open"
            or not lot.opens_at
            or not lot.closes_at
            or not aware_utc(lot.opens_at) <= now < aware_utc(lot.closes_at)
        ):
            db.session.rollback()
            return failure("lot_not_open", "Este lote não está aberto para lances.", status=409)
        authorization = db.session.scalar(
            select(AuctionAuthorization).where(
                AuctionAuthorization.id == authorization_id,
                AuctionAuthorization.lot_id == lot.id,
                AuctionAuthorization.status == "authorized",
            ).with_for_update()
        ) if authorization_id else None
        if not authorization or authorization.expires_at <= now:
            db.session.rollback()
            return failure(
                "auction_guarantee_required",
                "Autorize a garantia antes de enviar o lance.",
                status=409,
            )
        minimum = (
            lot.starting_bid_cents
            if lot.current_bid_cents is None
            else lot.current_bid_cents + lot.minimum_increment_cents
        )
        if amount < minimum:
            db.session.rollback()
            return failure(
                "bid_too_low",
                "O lance está abaixo do mínimo calculado pelo servidor.",
                status=409,
                fields={"amount_cents": [f"O valor mínimo é {minimum} centavos."]},
            )
        if amount != authorization.amount_cents:
            db.session.rollback()
            return failure(
                "auction_guarantee_amount_mismatch",
                "O valor não corresponde à garantia autorizada.",
                status=409,
            )
        bid = Bid(
            lot_id=lot.id,
            bidder_id=authorization.bidder_id,
            amount_cents=amount,
            idempotency_key=idempotency,
            request_hash=request_hash,
            terms_version=str(body["terms_version"]),
            terms_accepted_at=now,
            created_at=now,
            authorization_id=authorization.id,
        )
        db.session.add(bid)
        lot.current_bid_cents = amount
        db.session.commit()
        return success({"id": str(bid.id), "amount_cents": amount, "created_at": now}, status=201)
    except Exception:
        db.session.rollback()
        raise
