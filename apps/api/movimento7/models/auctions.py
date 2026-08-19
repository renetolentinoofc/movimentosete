from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import TimestampMixin, UUIDPrimaryKeyMixin


class Artwork(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "artworks"
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    artist_name: Mapped[str] = mapped_column(String(140), nullable=False)
    artist_profile_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id"), index=True)
    technique: Mapped[str | None] = mapped_column(String(140))
    dimensions: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(String(600))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)


class ArtworkMedia(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "artwork_media"
    artwork_id: Mapped[UUID] = mapped_column(ForeignKey("artworks.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    alt_text: Mapped[str] = mapped_column(String(180), nullable=False)
    credit: Mapped[str | None] = mapped_column(String(180))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuctionLot(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "auction_lots"
    __table_args__ = (
        CheckConstraint("starting_bid_cents >= 0", name="ck_lots_start_nonnegative"),
        CheckConstraint("minimum_increment_cents > 0", name="ck_lots_increment_positive"),
        Index("ix_lots_status_closes", "status", "closes_at"),
    )
    artwork_id: Mapped[UUID] = mapped_column(ForeignKey("artworks.id"), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    rules: Mapped[str | None] = mapped_column(Text)
    starting_bid_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_increment_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    current_bid_cents: Mapped[int | None] = mapped_column(Integer)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    winner_bid_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bids.id", use_alter=True, name="fk_auction_lots_winner_bid_id")
    )
    cancelled_reason: Mapped[str | None] = mapped_column(String(500))


class Bidder(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "bidders"
    display_alias: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Bid(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "bids"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_bids_amount_positive"),
        Index("ix_bids_lot_amount_created", "lot_id", "amount_cents", "created_at"),
    )
    lot_id: Mapped[UUID] = mapped_column(ForeignKey("auction_lots.id"), nullable=False)
    bidder_id: Mapped[UUID] = mapped_column(ForeignKey("bidders.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="valid", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    terms_version: Mapped[str] = mapped_column(String(30), nullable=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuctionLotStatusHistory(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "auction_lot_status_history"
    lot_id: Mapped[UUID] = mapped_column(ForeignKey("auction_lots.id"), nullable=False, index=True)
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
