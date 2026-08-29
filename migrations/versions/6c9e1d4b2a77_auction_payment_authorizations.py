"""Add Mercado Pago authorizations for auction bids."""

import sqlalchemy as sa
from alembic import op

revision = "6c9e1d4b2a77"
down_revision = "8b2d7f4c1a90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auction_authorizations",
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("bidder_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_order_id", sa.String(length=180), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=180), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lot_id"], ["auction_lots.id"]),
        sa.ForeignKeyConstraint(["bidder_id"], ["bidders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_order_id"),
        sa.UniqueConstraint("provider_payment_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_auction_authorizations_lot_id", "auction_authorizations", ["lot_id"])
    op.create_index("ix_auction_authorizations_bidder_id", "auction_authorizations", ["bidder_id"])
    op.create_index("ix_auction_authorizations_status", "auction_authorizations", ["status"])
    op.add_column("bids", sa.Column("authorization_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_bids_authorization_id", "bids", ["authorization_id"])
    op.create_foreign_key("fk_bids_authorization_id", "bids", "auction_authorizations", ["authorization_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_bids_authorization_id", "bids", type_="foreignkey")
    op.drop_constraint("uq_bids_authorization_id", "bids", type_="unique")
    op.drop_column("bids", "authorization_id")
    op.drop_index("ix_auction_authorizations_status", table_name="auction_authorizations")
    op.drop_index("ix_auction_authorizations_bidder_id", table_name="auction_authorizations")
    op.drop_index("ix_auction_authorizations_lot_id", table_name="auction_authorizations")
    op.drop_table("auction_authorizations")
