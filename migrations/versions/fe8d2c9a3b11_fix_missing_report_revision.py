"""fix missing report_revision on jobs

Revision ID: fe8d2c9a3b11
Revises: af25d3f4c9ab
Create Date: 2026-01-13 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fe8d2c9a3b11"
down_revision = "af25d3f4c9ab"
branch_labels = None
depends_on = None


def _has_column(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    if not _has_column(bind, "jobs", "report_revision"):
        with op.batch_alter_table("jobs") as batch_op:
            batch_op.add_column(
                sa.Column("report_revision", sa.Integer(), nullable=False, server_default=sa.text("0"))
            )


def downgrade():
    bind = op.get_bind()
    if _has_column(bind, "jobs", "report_revision"):
        with op.batch_alter_table("jobs") as batch_op:
            batch_op.drop_column("report_revision")
