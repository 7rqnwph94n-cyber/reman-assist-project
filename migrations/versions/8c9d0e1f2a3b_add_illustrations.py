"""add_illustrations

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2025-01-19 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8c9d0e1f2a3b"
down_revision = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_template_sections_template_id", "template_sections", ["template_id"])

    op.create_table(
        "illustration_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("engine_tag", sa.String(length=128), nullable=True),
        sa.Column("image_path", sa.String(length=255), nullable=False),
        sa.Column("natural_w", sa.Integer(), nullable=True),
        sa.Column("natural_h", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("display_config_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "illustration_part_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("illustration_page_id", sa.Integer(), nullable=False),
        sa.Column("pos", sa.Integer(), nullable=False),
        sa.Column("part_no", sa.String(length=120), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("designation", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["illustration_page_id"], ["illustration_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_illustration_part_rows_page", "illustration_part_rows", ["illustration_page_id"])

    op.create_table(
        "illustration_pos_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("illustration_page_id", sa.Integer(), nullable=False),
        sa.Column("pos", sa.Integer(), nullable=False),
        sa.Column("x_norm", sa.Float(), nullable=False),
        sa.Column("y_norm", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["illustration_page_id"], ["illustration_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_illustration_pos_labels_page", "illustration_pos_labels", ["illustration_page_id"])

    op.create_table(
        "illustration_hotspots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("illustration_page_id", sa.Integer(), nullable=False),
        sa.Column("pos", sa.Integer(), nullable=False),
        sa.Column("shape_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["illustration_page_id"], ["illustration_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_illustration_hotspots_page", "illustration_hotspots", ["illustration_page_id"])

    op.create_table(
        "template_section_illustrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_section_id", sa.Integer(), nullable=False),
        sa.Column("illustration_page_id", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["template_section_id"], ["template_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["illustration_page_id"], ["illustration_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_template_section_illustrations_section", "template_section_illustrations", ["template_section_id"])


def downgrade():
    op.drop_index("ix_template_section_illustrations_section", table_name="template_section_illustrations")
    op.drop_table("template_section_illustrations")
    op.drop_index("ix_illustration_hotspots_page", table_name="illustration_hotspots")
    op.drop_table("illustration_hotspots")
    op.drop_index("ix_illustration_pos_labels_page", table_name="illustration_pos_labels")
    op.drop_table("illustration_pos_labels")
    op.drop_index("ix_illustration_part_rows_page", table_name="illustration_part_rows")
    op.drop_table("illustration_part_rows")
    op.drop_table("illustration_pages")
    op.drop_index("ix_template_sections_template_id", table_name="template_sections")
    op.drop_table("template_sections")
