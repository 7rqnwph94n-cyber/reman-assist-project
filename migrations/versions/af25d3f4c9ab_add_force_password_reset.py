"""Add force_password_reset to users

Revision ID: af25d3f4c9ab
Revises: ab12cd34ef56
Create Date: 2026-01-13 12:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "af25d3f4c9ab"
down_revision = "ab12cd34ef56"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    with op.batch_alter_table("users") as batch_op:
        default_expr = sa.text("false") if is_postgres else sa.text("0")
        batch_op.add_column(
            sa.Column(
                "force_password_reset",
                sa.Boolean(),
                nullable=False,
                server_default=default_expr,
            )
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("force_password_reset", server_default=None)


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("force_password_reset")
