from datetime import UTC, datetime

from flask import Blueprint, current_app, request
from sqlalchemy import select

from ..extensions import db
from ..http import failure, success
from ..models import Artwork, ArtworkMedia, AuctionLot, Bid, Bidder
from ..security import rate_limited
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


@bp.post("/auction-lots/<lot_id>/bids")
def create_bid(lot_id: str):
    if not current_app.config["AUCTION_BIDDING_ENABLED"]:
        return failure(
            "bidding_disabled",
            "Os lotes estão em modo de exposição. Lances ainda não estão habilitados.",
            status=409,
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
    if existing:
        return success(
            {
                "id": str(existing.id),
                "amount_cents": existing.amount_cents,
                "created_at": existing.created_at,
                "replayed": True,
            }
        )
    body = request.get_json(silent=True) or {}
    try:
        amount = int(body.get("amount_cents", 0))
    except (TypeError, ValueError):
        amount = 0
    phone = normalize_phone(str(body.get("phone", "")))
    fields = {}
    for key in ("name", "email", "terms_version"):
        if not str(body.get(key, "")).strip():
            fields[key] = ["Campo obrigatório."]
    if not phone:
        fields["phone"] = ["WhatsApp inválido."]
    if body.get("terms_accepted") is not True:
        fields["terms_accepted"] = ["Aceite as regras do leilão."]
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
        bidder = Bidder(
            display_alias=f"Participante {str(lot.id)[-4:].upper()}",
            name=str(body["name"]).strip(),
            email=str(body["email"]).strip().lower(),
            phone_e164=phone,
        )
        db.session.add(bidder)
        db.session.flush()
        bid = Bid(
            lot_id=lot.id,
            bidder_id=bidder.id,
            amount_cents=amount,
            idempotency_key=idempotency,
            terms_version=str(body["terms_version"]),
            terms_accepted_at=now,
            created_at=now,
        )
        db.session.add(bid)
        lot.current_bid_cents = amount
        db.session.commit()
        return success({"id": str(bid.id), "amount_cents": amount, "created_at": now}, status=201)
    except Exception:
        db.session.rollback()
        raise
