from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from .base import TimestampMixin, UUIDPrimaryKeyMixin


class AdminUser(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    roles: Mapped[list["Role"]] = relationship(secondary="user_roles", back_populates="users")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "roles"

    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    users: Mapped[list[AdminUser]] = relationship(secondary="user_roles", back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions", back_populates="roles"
    )


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "permissions"

    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    roles: Mapped[list[Role]] = relationship(
        secondary="role_permissions", back_populates="permissions"
    )


class UserRole(db.Model):
    __tablename__ = "user_roles"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class AdminSession(UUIDPrimaryKeyMixin, TimestampMixin, db.Model):
    __tablename__ = "admin_sessions"
    __table_args__ = (Index("ix_admin_sessions_user_expires", "user_id", "expires_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token_hash: Mapped[str | None] = mapped_column(String(64))
    user_session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    user: Mapped[AdminUser] = relationship()


class LoginAttempt(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_subject_created", "subject_hash", "created_at"),)

    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdminPasswordReset(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "admin_password_resets"
    __table_args__ = (Index("ix_admin_password_resets_user_expires", "user_id", "expires_at"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user: Mapped[AdminUser] = relationship()


class AuditLog(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_resource_created", "resource_type", "created_at"),
        Index("ix_audit_action_created", "action", "created_at"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class IdempotencyKey(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key_hash", name="uq_idempotency_scope_key"),)

    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RateLimitEvent(UUIDPrimaryKeyMixin, db.Model):
    __tablename__ = "rate_limit_events"
    __table_args__ = (Index("ix_rate_limit_bucket_created", "bucket_hash", "created_at"),)

    bucket_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
