"""Store a normalized request hash for bid idempotency."""

from alembic import op
import sqlalchemy as sa

revision = "8b2d7f4c1a90"
down_revision = "4f7d9c2a6b11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bids", sa.Column("request_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("bids", "request_hash")
