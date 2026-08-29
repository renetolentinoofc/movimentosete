"""prevent duplicate variants in a cart

Revision ID: 3a5c8b2e1f44
Revises: d8a731c0b112
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3a5c8b2e1f44"
down_revision: str | None = "d8a731c0b112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the newest row when old data contains duplicates before adding the constraint.
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            """
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY cart_id, variant_id ORDER BY created_at DESC, id DESC
                ) AS row_number
                FROM cart_items
            ) duplicate_rows
            WHERE row_number > 1
            """
        )
    ).scalars().all()
    if duplicates:
        bind.execute(sa.delete(sa.table("cart_items", sa.column("id"))).where(
            sa.column("id").in_(duplicates)
        ))
    op.create_unique_constraint("uq_cart_item_cart_variant", "cart_items", ["cart_id", "variant_id"])


def downgrade() -> None:
    op.drop_constraint("uq_cart_item_cart_variant", "cart_items", type_="unique")
