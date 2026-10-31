"""merge heads f2a3b4c5d6e7 and fe8d2c9a3b11

Revision ID: 9c2d1e7f4a6b
Revises: f2a3b4c5d6e7, fe8d2c9a3b11
Create Date: 2026-01-13 12:20:00.000000
"""

from alembic import op  # noqa: F401


# revision identifiers, used by Alembic.
revision = "9c2d1e7f4a6b"
down_revision = ("f2a3b4c5d6e7", "fe8d2c9a3b11")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
