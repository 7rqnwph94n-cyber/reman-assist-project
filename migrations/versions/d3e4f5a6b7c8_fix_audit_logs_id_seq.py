"""Fix audit_logs id sequence for Postgres

Revision ID: d3e4f5a6b7c8
Revises: c7d8e9f0a1b2
Create Date: 2026-01-13 15:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "d3e4f5a6b7c8"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE SEQUENCE IF NOT EXISTS audit_logs_id_seq")
    op.execute("ALTER SEQUENCE audit_logs_id_seq OWNED BY audit_logs.id")
    op.execute("ALTER TABLE audit_logs ALTER COLUMN id SET DEFAULT nextval('audit_logs_id_seq')")
    op.execute(
        "SELECT setval('audit_logs_id_seq', COALESCE((SELECT MAX(id) FROM audit_logs), 1), true)"
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE audit_logs ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS audit_logs_id_seq")
