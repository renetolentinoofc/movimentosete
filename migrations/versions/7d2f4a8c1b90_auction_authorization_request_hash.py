"""Store auction authorization request hashes for idempotency."""

import sqlalchemy as sa
from alembic import op

revision = "7d2f4a8c1b90"
down_revision = "6c9e1d4b2a77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auction_authorizations", sa.Column("request_hash", sa.String(length=64), nullable=True))
    op.execute("UPDATE auction_authorizations SET request_hash = '' WHERE request_hash IS NULL")
    op.alter_column("auction_authorizations", "request_hash", nullable=False)


def downgrade() -> None:
    op.drop_column("auction_authorizations", "request_hash")
