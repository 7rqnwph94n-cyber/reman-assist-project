"""add bundles to template_items"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'zz_add_bundles_template_item'
down_revision = 'zz_add_supersedes_template_item'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('template_items', sa.Column('bundles', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('template_items', 'bundles')
