"""add_templateitem_assembly_fields

Revision ID: 6f2c1a0b9d7e
Revises: 462e693b8825
Create Date: 2026-01-27 14:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f2c1a0b9d7e'
down_revision = '462e693b8825'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('template_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requires_torque', sa.Boolean(), nullable=True, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('requires_build_measure', sa.Boolean(), nullable=True, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('requires_photo', sa.Boolean(), nullable=True, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('torque_value', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('torque_unit', sa.String(length=16), nullable=True, server_default='Nm'))
        batch_op.add_column(sa.Column('torque_sequence', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('assembly_notes', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('template_items', schema=None) as batch_op:
        batch_op.drop_column('assembly_notes')
        batch_op.drop_column('torque_sequence')
        batch_op.drop_column('torque_unit')
        batch_op.drop_column('torque_value')
        batch_op.drop_column('requires_photo')
        batch_op.drop_column('requires_build_measure')
        batch_op.drop_column('requires_torque')
