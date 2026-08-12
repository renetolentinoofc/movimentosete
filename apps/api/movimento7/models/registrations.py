from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import TimestampMixin, UUIDPrimaryKeyMixin


class EventEdition(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "event_editions"

    name: Mapped[str] = mapped_column(String(140), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(180))
    address: Mapped[str | None] = mapped_column(String(300))
    map_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    capacity: Mapped[int | None] = mapped_column(Integer)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=730)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ParticipationCategory(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "participation_categories"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(400))
    extra_fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    accepts_file: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    accepts_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Registration(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "registrations"
    __table_args__ = (
        Index("ix_registrations_status_created", "status", "created_at"),
        Index("ix_registrations_edition_category", "edition_id", "category_id"),
    )

    protocol: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    upload_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    edition_id: Mapped[UUID | None] = mapped_column(ForeignKey("event_editions.id"), index=True)
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("participation_categories.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(140), nullable=False)
    professional_name: Mapped[str | None] = mapped_column(String(140))
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    instagram_handle: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    presentation: Mapped[str] = mapped_column(Text, nullable=False)
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    extra_data_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received", index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal", index=True)
    assigned_to_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"), index=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    privacy_version: Mapped[str] = mapped_column(String(30), nullable=False)
    consent_purpose: Mapped[str] = mapped_column(String(160), nullable=False)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[ParticipationCategory] = relationship()


class RegistrationFile(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "registration_files"

    registration_id: Mapped[UUID] = mapped_column(
        ForeignKey("registrations.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="ready")
    reconciliation_status: Mapped[str] = mapped_column(String(30), nullable=False, default="synced")


class RegistrationNote(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "registration_notes"
    registration_id: Mapped[UUID] = mapped_column(
        ForeignKey("registrations.id"), nullable=False, index=True
    )
    author_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RegistrationStatusHistory(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "registration_status_history"
    registration_id: Mapped[UUID] = mapped_column(
        ForeignKey("registrations.id"), nullable=False, index=True
    )
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    old_status: Mapped[str | None] = mapped_column(String(30))
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Profile(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "profiles"
    registration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("registrations.id"), unique=True
    )
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(140), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    instagram_handle: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfileCategory(db.Model):
    __tablename__ = "profile_categories"
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("participation_categories.id", ondelete="CASCADE"), primary_key=True
    )


class PortfolioAsset(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "portfolio_assets"
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)
    alt_text: Mapped[str] = mapped_column(String(180), nullable=False)
    credit: Mapped[str | None] = mapped_column(String(180))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CommunicationLog(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "communication_logs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_communication_idempotency"),)
    registration_id: Mapped[UUID | None] = mapped_column(ForeignKey("registrations.id"), index=True)
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    recipient_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
