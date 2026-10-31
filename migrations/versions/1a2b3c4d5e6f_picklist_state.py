"""Add pick/issue/return fields to pick_list_items

Revision ID: 1a2b3c4d5e6f
Revises: 7a002b9dbc0e
Create Date: 2025-12-07
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1a2b3c4d5e6f"
down_revision = "7a002b9dbc0e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pick_list_items") as batch_op:
        batch_op.add_column(sa.Column("picked", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("issued_qty", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("returned_qty", sa.Integer(), nullable=False, server_default="0"))

    # drop server defaults
    with op.batch_alter_table("pick_list_items") as batch_op:
        batch_op.alter_column("picked", server_default=None)
        batch_op.alter_column("issued_qty", server_default=None)
        batch_op.alter_column("returned_qty", server_default=None)


def downgrade():
    with op.batch_alter_table("pick_list_items") as batch_op:
        batch_op.drop_column("returned_qty")
        batch_op.drop_column("issued_qty")
        batch_op.drop_column("picked")
