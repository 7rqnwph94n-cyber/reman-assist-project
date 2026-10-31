"""add BACKORDER to stockstatusenum

Revision ID: 2b7a9c1e5d10
Revises: 9c2d1e7f4a6b
Create Date: 2026-01-13 12:30:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "2b7a9c1e5d10"
down_revision = "9c2d1e7f4a6b"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE stockstatusenum ADD VALUE IF NOT EXISTS 'BACKORDER'")


def downgrade():
    # Enum value removal isn't supported in PostgreSQL; no-op.
    pass
