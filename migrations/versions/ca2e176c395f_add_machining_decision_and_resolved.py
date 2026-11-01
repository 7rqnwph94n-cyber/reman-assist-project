"""add machining decision and resolved flag

Revision ID: ca2e176c395f
Revises: a1b2c3d4e5f6
Create Date: 2026-01-27 19:35:26.022865

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ca2e176c395f'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE decisionenum ADD VALUE IF NOT EXISTS 'MACHINING'")
    with op.batch_alter_table('survey_items', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_resolved', sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table('survey_items', schema=None) as batch_op:
        batch_op.alter_column('is_resolved', server_default=None)


def downgrade():
    with op.batch_alter_table('survey_items', schema=None) as batch_op:
        batch_op.drop_column('is_resolved')
