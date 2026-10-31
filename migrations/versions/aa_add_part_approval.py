"""Add approval fields to part_requirements

Revision ID: aa_add_part_approval
Revises: 1a2b3c4d5e6f_picklist_state
Create Date: 2025-03-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aa_add_part_approval"
down_revision = "zz_add_bundles_template_item"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("part_requirements") as batch_op:
        batch_op.add_column(sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("approved_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_part_requirements_approved_by_users",
            "users",
            ["approved_by_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("part_requirements") as batch_op:
        batch_op.drop_constraint("fk_part_requirements_approved_by_users", type_="foreignkey")
        batch_op.drop_column("approved_at")
        batch_op.drop_column("approved_by_id")
        batch_op.drop_column("approved")
