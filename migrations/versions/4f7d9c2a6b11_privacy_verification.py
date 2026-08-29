"""add public privacy request verification

Revision ID: 4f7d9c2a6b11
Revises: 3a5c8b2e1f44
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f7d9c2a6b11"
down_revision: str | None = "3a5c8b2e1f44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("privacy_requests", sa.Column("requester_email", sa.String(length=180), nullable=True))
    op.add_column(
        "privacy_requests", sa.Column("verification_token_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "privacy_requests",
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("privacy_requests", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    # Existing rows were created by the internal administrative screen and have
    # no public verification token. Keep them reviewable while requiring new
    # public requests to populate all fields.
    op.execute(
        sa.text(
            "UPDATE privacy_requests SET "
            "requester_email = 'legacy-' || CAST(id AS VARCHAR) || '@invalid.local', "
            "verification_token_hash = 'legacy-' || REPLACE(CAST(id AS VARCHAR), '-', ''), "
            "verification_expires_at = CURRENT_TIMESTAMP "
            "WHERE requester_email IS NULL"
        )
    )
    op.create_unique_constraint(
        "uq_privacy_request_verification_token", "privacy_requests", ["verification_token_hash"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_privacy_request_verification_token", "privacy_requests", type_="unique")
    op.drop_column("privacy_requests", "verified_at")
    op.drop_column("privacy_requests", "verification_expires_at")
    op.drop_column("privacy_requests", "verification_token_hash")
    op.drop_column("privacy_requests", "requester_email")
