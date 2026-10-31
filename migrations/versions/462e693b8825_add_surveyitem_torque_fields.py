"""add_surveyitem_torque_fields

Revision ID: 462e693b8825
Revises: 9f1a2b3c4d5e
Create Date: 2026-01-27 13:50:36.424590

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '462e693b8825'
down_revision = '9f1a2b3c4d5e'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'measurement_audit_logs' not in existing_tables:
        op.create_table(
            'measurement_audit_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('survey_item_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('field_name', sa.String(length=64), nullable=False),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('change_reason', sa.Text(), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['survey_item_id'], ['survey_items.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'measurement_audit_logs' in existing_tables or 'measurement_audit_logs' not in existing_tables:
        existing_indexes = {idx['name'] for idx in inspector.get_indexes('measurement_audit_logs')}
        with op.batch_alter_table('measurement_audit_logs', schema=None) as batch_op:
            idx_name = batch_op.f('ix_measurement_audit_logs_survey_item_id')
            if idx_name not in existing_indexes:
                batch_op.create_index(idx_name, ['survey_item_id'], unique=False)
            idx_name = batch_op.f('ix_measurement_audit_logs_timestamp')
            if idx_name not in existing_indexes:
                batch_op.create_index(idx_name, ['timestamp'], unique=False)
            idx_name = batch_op.f('ix_measurement_audit_logs_user_id')
            if idx_name not in existing_indexes:
                batch_op.create_index(idx_name, ['user_id'], unique=False)

    existing_columns = {col['name'] for col in inspector.get_columns('survey_items')}
    with op.batch_alter_table('survey_items', schema=None) as batch_op:
        if 'torque_value' not in existing_columns:
            batch_op.add_column(sa.Column('torque_value', sa.Float(), nullable=True))
        if 'torque_unit' not in existing_columns:
            batch_op.add_column(sa.Column('torque_unit', sa.String(length=16), nullable=True, server_default='Nm'))
        if 'torque_sequence' not in existing_columns:
            batch_op.add_column(sa.Column('torque_sequence', sa.Integer(), nullable=True))
        if 'torque_confirmed' not in existing_columns:
            batch_op.add_column(sa.Column('torque_confirmed', sa.Boolean(), nullable=True, server_default=sa.text('0')))


def downgrade():
    with op.batch_alter_table('survey_items', schema=None) as batch_op:
        batch_op.drop_column('torque_confirmed')
        batch_op.drop_column('torque_sequence')
        batch_op.drop_column('torque_unit')
        batch_op.drop_column('torque_value')

    with op.batch_alter_table('measurement_audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_measurement_audit_logs_user_id'))
        batch_op.drop_index(batch_op.f('ix_measurement_audit_logs_timestamp'))
        batch_op.drop_index(batch_op.f('ix_measurement_audit_logs_survey_item_id'))

    op.drop_table('measurement_audit_logs')
