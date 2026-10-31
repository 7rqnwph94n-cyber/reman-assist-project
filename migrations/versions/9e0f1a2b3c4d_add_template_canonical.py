"""add_template_canonical_parts_occurrences

Revision ID: 9e0f1a2b3c4d
Revises: 9d0e1f2a3b4c
Create Date: 2025-01-20 19:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9e0f1a2b3c4d"
down_revision = "9d0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_parts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("part_no", sa.String(length=128), nullable=False),
        sa.Column("normalized_part_no", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_template_parts_template_id", "template_parts", ["template_id"])
    op.create_index("ix_template_parts_normalized", "template_parts", ["normalized_part_no"])

    op.create_table(
        "template_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("template_part_id", sa.Integer(), nullable=False),
        sa.Column("template_item_id", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=128), nullable=True),
        sa.Column("pos", sa.Integer(), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_part_id"], ["template_parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_item_id"], ["template_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_template_occurrences_template_id", "template_occurrences", ["template_id"])
    op.create_index("ix_template_occurrences_part_id", "template_occurrences", ["template_part_id"])
    op.create_index("ix_template_occurrences_item_id", "template_occurrences", ["template_item_id"])


def downgrade():
    op.drop_index("ix_template_occurrences_item_id", table_name="template_occurrences")
    op.drop_index("ix_template_occurrences_part_id", table_name="template_occurrences")
    op.drop_index("ix_template_occurrences_template_id", table_name="template_occurrences")
    op.drop_table("template_occurrences")
    op.drop_index("ix_template_parts_normalized", table_name="template_parts")
    op.drop_index("ix_template_parts_template_id", table_name="template_parts")
    op.drop_table("template_parts")
