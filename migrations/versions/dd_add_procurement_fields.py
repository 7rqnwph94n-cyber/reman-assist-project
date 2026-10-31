"""Add procurement tracking fields and backorder status

Revision ID: dd_add_procurement_fields
Revises: cc_epicor_settings
Create Date: 2026-01-01 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "dd_add_procurement_fields"
down_revision = "cc_epicor_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    old_enum = sa.Enum(
        "PENDING",
        "IN_STOCK",
        "TO_ORDER",
        "ORDERED",
        "RECEIVED",
        "FITTED",
        "NOT_REQUIRED",
        name="stockstatusenum",
    )
    new_enum = sa.Enum(
        "PENDING",
        "IN_STOCK",
        "TO_ORDER",
        "ORDERED",
        "RECEIVED",
        "BACKORDER",
        "FITTED",
        "NOT_REQUIRED",
        name="stockstatusenum",
    )

    if is_postgres:
        op.execute("ALTER TYPE stockstatusenum ADD VALUE IF NOT EXISTS 'BACKORDER'")
        with op.batch_alter_table("part_requirements") as batch_op:
            batch_op.add_column(sa.Column("backorder_reason", sa.Text(), nullable=True))
            batch_op.add_column(
                sa.Column("qty_received", sa.Integer(), nullable=False, server_default="0")
            )
            batch_op.add_column(sa.Column("received_at", sa.DateTime(), nullable=True))
            batch_op.add_column(sa.Column("received_by_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_part_requirements_received_by_users",
                "users",
                ["received_by_id"],
                ["id"],
            )
    else:
        with op.batch_alter_table("part_requirements") as batch_op:
            batch_op.alter_column(
                "stock_status",
                existing_type=old_enum,
                type_=new_enum,
                existing_nullable=False,
            )
            batch_op.add_column(sa.Column("backorder_reason", sa.Text(), nullable=True))
            batch_op.add_column(
                sa.Column("qty_received", sa.Integer(), nullable=False, server_default="0")
            )
            batch_op.add_column(sa.Column("received_at", sa.DateTime(), nullable=True))
            batch_op.add_column(sa.Column("received_by_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_part_requirements_received_by_users",
                "users",
                ["received_by_id"],
                ["id"],
            )


def downgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    old_enum = sa.Enum(
        "PENDING",
        "IN_STOCK",
        "TO_ORDER",
        "ORDERED",
        "RECEIVED",
        "FITTED",
        "NOT_REQUIRED",
        name="stockstatusenum",
    )
    new_enum = sa.Enum(
        "PENDING",
        "IN_STOCK",
        "TO_ORDER",
        "ORDERED",
        "RECEIVED",
        "BACKORDER",
        "FITTED",
        "NOT_REQUIRED",
        name="stockstatusenum",
    )
    with op.batch_alter_table("part_requirements") as batch_op:
        batch_op.drop_constraint("fk_part_requirements_received_by_users", type_="foreignkey")
        batch_op.drop_column("received_by_id")
        batch_op.drop_column("received_at")
        batch_op.drop_column("qty_received")
        batch_op.drop_column("backorder_reason")
        if not is_postgres:
            batch_op.alter_column(
                "stock_status",
                existing_type=new_enum,
                type_=old_enum,
                existing_nullable=False,
            )
