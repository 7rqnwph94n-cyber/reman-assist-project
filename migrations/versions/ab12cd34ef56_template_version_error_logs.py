"""Add template version snapshot and error logs

Revision ID: ab12cd34ef56
Revises: ff2b9b1a3c7d
Create Date: 2026-01-01 22:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ab12cd34ef56"
down_revision = "ff2b9b1a3c7d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("templates") as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("templates") as batch_op:
        batch_op.alter_column("version", server_default=None)

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("template_version", sa.Integer(), nullable=True))

    # backfill job template_version from current template version
    try:
        op.execute(
            "UPDATE jobs SET template_version = (SELECT version FROM templates WHERE templates.id = jobs.template_id) "
            "WHERE template_version IS NULL AND template_id IS NOT NULL"
        )
    except Exception:
        pass

    op.create_table(
        "error_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_error_logs_created_at", "error_logs", ["created_at"])


def downgrade():
    op.drop_index("ix_error_logs_created_at", table_name="error_logs")
    op.drop_table("error_logs")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("template_version")

    with op.batch_alter_table("templates") as batch_op:
        batch_op.drop_column("version")
