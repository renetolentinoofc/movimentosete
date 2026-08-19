"""email notifications and password resets

Revision ID: 9c2f42d8137a
Revises: 784a42a09e36
Create Date: 2026-08-15 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c2f42d8137a"
down_revision: str | None = "784a42a09e36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("registrations", sa.Column("email", sa.String(length=180), nullable=True))
    op.create_index(op.f("ix_registrations_email"), "registrations", ["email"], unique=False)
    op.create_table(
        "admin_password_resets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_admin_password_resets_user_expires",
        "admin_password_resets",
        ["user_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_password_resets_used_at"),
        "admin_password_resets",
        ["used_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_password_resets_used_at"), table_name="admin_password_resets")
    op.drop_index(
        "ix_admin_password_resets_user_expires", table_name="admin_password_resets"
    )
    op.drop_table("admin_password_resets")
    op.drop_index(op.f("ix_registrations_email"), table_name="registrations")
    op.drop_column("registrations", "email")
