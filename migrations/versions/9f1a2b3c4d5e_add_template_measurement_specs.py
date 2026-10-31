"""add_template_measurement_specs

Revision ID: 9f1a2b3c4d5e
Revises: 9e0f1a2b3c4d
Create Date: 2025-01-25 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9f1a2b3c4d5e"
down_revision = "9e0f1a2b3c4d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_measurement_specs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_item_id", sa.Integer(), nullable=False),
        sa.Column("instance_index", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["template_item_id"], ["template_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_item_id", "instance_index", name="uq_template_measurement_specs_item_instance"),
    )
    op.create_index(
        "ix_template_measurement_specs_item_id",
        "template_measurement_specs",
        ["template_item_id"],
    )


def downgrade():
    op.drop_index("ix_template_measurement_specs_item_id", table_name="template_measurement_specs")
    op.drop_table("template_measurement_specs")
