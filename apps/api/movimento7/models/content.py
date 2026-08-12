from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from .base import TimestampMixin, UUIDPrimaryKeyMixin


class GalleryAlbum(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "gallery_albums"
    edition_id: Mapped[UUID | None] = mapped_column(ForeignKey("event_editions.id"), index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GalleryMedia(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "gallery_media"
    __table_args__ = (Index("ix_gallery_status_order", "status", "display_order"),)
    album_id: Mapped[UUID] = mapped_column(ForeignKey("gallery_albums.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    safe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(600))
    alt_text: Mapped[str] = mapped_column(String(180), nullable=False)
    credit: Mapped[str | None] = mapped_column(String(180))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="processing")
    reconciliation_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GalleryTag(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "gallery_tags"
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class GalleryMediaTag(db.Model):
    __tablename__ = "gallery_media_tags"
    media_id: Mapped[UUID] = mapped_column(ForeignKey("gallery_media.id"), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(ForeignKey("gallery_tags.id"), primary_key=True)


class Partner(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "partners"
    name: Mapped[str] = mapped_column(String(140), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(String(500))
    logo_path: Mapped[str] = mapped_column(String(500), nullable=False)
    logo_alt: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="partner")
    level: Mapped[str | None] = mapped_column(String(60))
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PartnerEdition(db.Model):
    __tablename__ = "partner_editions"
    partner_id: Mapped[UUID] = mapped_column(ForeignKey("partners.id"), primary_key=True)
    edition_id: Mapped[UUID] = mapped_column(ForeignKey("event_editions.id"), primary_key=True)


class ContentEntry(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "content_entries"
    key: Mapped[str] = mapped_column(String(140), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400))
    current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "content_versions.id",
            use_alter=True,
            name="fk_content_entries_current_version_id",
        )
    )


class ContentVersion(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "content_versions"
    __table_args__ = (UniqueConstraint("entry_id", "version", name="uq_content_entry_version"),)
    entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("content_entries.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SiteSetting(TimestampMixin, db.Model):
    __tablename__ = "site_settings"
    key: Mapped[str] = mapped_column(String(140), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))


class SocialLink(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "social_links"
    network: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ContactMessage(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "contact_messages"
    __table_args__ = (Index("ix_contact_status_created", "status", "created_at"),)
    protocol: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(140), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    privacy_version: Mapped[str] = mapped_column(String(30), nullable=False)


class IntegrationCredential(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "integration_credentials"
    provider: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    encrypted_payload: Mapped[bytes] = mapped_column(nullable=False)
    key_version: Mapped[str] = mapped_column(String(30), nullable=False)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class OAuthState(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "oauth_states"
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    encrypted_verifier: Mapped[bytes] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaReconciliationTask(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "media_reconciliation_tasks"
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(index=True)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))


class PrivacyRequest(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "privacy_requests"
    protocol: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    resolved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataExport(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "data_exports"
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    export_type: Mapped[str] = mapped_column(String(40), nullable=False)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    storage_key: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupRecord(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "backup_records"
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    location_label: Mapped[str] = mapped_column(String(180), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
