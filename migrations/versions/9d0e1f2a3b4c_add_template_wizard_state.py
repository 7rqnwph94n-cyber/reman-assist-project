"""add_template_wizard_state

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2025-01-20 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9d0e1f2a3b4c"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "template_wizard_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("step_data", sa.JSON(), nullable=True),
        sa.Column("step_status", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id"),
    )
    op.create_index("ix_template_wizard_states_template_id", "template_wizard_states", ["template_id"])


def downgrade():
    op.drop_index("ix_template_wizard_states_template_id", table_name="template_wizard_states")
    op.drop_table("template_wizard_states")
