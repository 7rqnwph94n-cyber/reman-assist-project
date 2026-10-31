"""add supersedes to template_items"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'zz_add_supersedes_template_item'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('template_items', sa.Column('supersedes', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('template_items', 'supersedes')
