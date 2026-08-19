"""contact inbox

Revision ID: d8a731c0b112
Revises: 9c2f42d8137a
Create Date: 2026-08-19 11:00:00
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "d8a731c0b112"
down_revision: str | None = "9c2f42d8137a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTACT_PERMISSION_IDS = {
    "contacts.read": UUID("4e5127d1-5ac7-4e0b-8f53-c121977a45e1"),
    "contacts.manage": UUID("c7372878-321e-45ea-98fc-89d61054f44a"),
}


def upgrade() -> None:
    with op.batch_alter_table("contact_messages") as batch_op:
        batch_op.add_column(sa.Column("assigned_to_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_contact_messages_assigned_to_id_admin_users",
            "admin_users",
            ["assigned_to_id"],
            ["id"],
        )
        batch_op.create_index(
            op.f("ix_contact_messages_assigned_to_id"),
            ["assigned_to_id"],
            unique=False,
        )
    with op.batch_alter_table("communication_logs") as batch_op:
        batch_op.add_column(sa.Column("contact_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_communication_logs_contact_id_contact_messages",
            "contact_messages",
            ["contact_id"],
            ["id"],
        )
        batch_op.create_index(
            op.f("ix_communication_logs_contact_id"),
            ["contact_id"],
            unique=False,
        )
    op.create_table(
        "contact_notes",
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contact_notes_contact_id"),
        "contact_notes",
        ["contact_id"],
        unique=False,
    )
    op.create_table(
        "contact_status_history",
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contact_status_history_contact_id"),
        "contact_status_history",
        ["contact_id"],
        unique=False,
    )
    op.create_table(
        "contact_replies",
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("communication_log_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("delivery_status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["communication_log_id"], ["communication_logs.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contact_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("communication_log_id"),
    )
    op.create_index(
        op.f("ix_contact_replies_contact_id"),
        "contact_replies",
        ["contact_id"],
        unique=False,
    )
    seed_permissions()


def seed_permissions() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("slug", sa.String()),
        sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table("roles", sa.column("id", sa.Uuid()), sa.column("slug", sa.String()))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Uuid()),
        sa.column("permission_id", sa.Uuid()),
    )
    descriptions = {
        "contacts.read": "Consultar mensagens de contato",
        "contacts.manage": "Operar mensagens, responsáveis, notas e respostas",
    }
    for slug, permission_id in CONTACT_PERMISSION_IDS.items():
        existing = bind.execute(
            sa.select(permissions.c.id).where(permissions.c.slug == slug)
        ).scalar_one_or_none()
        if existing is None:
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    slug=slug,
                    description=descriptions[slug],
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            CONTACT_PERMISSION_IDS[slug] = existing
    role_rows = bind.execute(
        sa.select(roles.c.id, roles.c.slug).where(
            roles.c.slug.in_(("administrador", "atendimento"))
        )
    ).all()
    for role_id, _role_slug in role_rows:
        for permission_id in CONTACT_PERMISSION_IDS.values():
            exists = bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if not exists:
                bind.execute(
                    role_permissions.insert().values(
                        role_id=role_id, permission_id=permission_id
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    role_permissions = sa.table(
        "role_permissions",
        sa.column("permission_id", sa.Uuid()),
    )
    permissions = sa.table("permissions", sa.column("id", sa.Uuid()))
    ids = tuple(CONTACT_PERMISSION_IDS.values())
    bind.execute(role_permissions.delete().where(role_permissions.c.permission_id.in_(ids)))
    bind.execute(permissions.delete().where(permissions.c.id.in_(ids)))
    op.drop_index(op.f("ix_contact_replies_contact_id"), table_name="contact_replies")
    op.drop_table("contact_replies")
    op.drop_index(
        op.f("ix_contact_status_history_contact_id"),
        table_name="contact_status_history",
    )
    op.drop_table("contact_status_history")
    op.drop_index(op.f("ix_contact_notes_contact_id"), table_name="contact_notes")
    op.drop_table("contact_notes")
    with op.batch_alter_table("communication_logs") as batch_op:
        batch_op.drop_index(op.f("ix_communication_logs_contact_id"))
        batch_op.drop_constraint(
            "fk_communication_logs_contact_id_contact_messages", type_="foreignkey"
        )
        batch_op.drop_column("contact_id")
    with op.batch_alter_table("contact_messages") as batch_op:
        batch_op.drop_index(op.f("ix_contact_messages_assigned_to_id"))
        batch_op.drop_constraint(
            "fk_contact_messages_assigned_to_id_admin_users", type_="foreignkey"
        )
        batch_op.drop_column("assigned_to_id")
