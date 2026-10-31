"""Add barcode to store_items

Revision ID: b1c2d3e4f5a6
Revises: af25d3f4c9ab
Create Date: 2026-01-13 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f5a6"
down_revision = "af25d3f4c9ab"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("store_items") as batch_op:
        batch_op.add_column(sa.Column("barcode", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_store_items_barcode", ["barcode"])


def downgrade():
    with op.batch_alter_table("store_items") as batch_op:
        batch_op.drop_constraint("uq_store_items_barcode", type_="unique")
        batch_op.drop_column("barcode")
