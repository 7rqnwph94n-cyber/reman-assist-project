"""job indexes and measurement audit composite index

Revision ID: 8a1b2c3d4e5f
Revises: 7c1d2e3f4a5b
Create Date: 2026-01-27 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8a1b2c3d4e5f'
down_revision = '7c1d2e3f4a5b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jobs_serial_number'), ['serial_number'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_customer_name'), ['customer_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_jobs_engine_type'), ['engine_type'], unique=False)

    with op.batch_alter_table('measurement_audit_logs', schema=None) as batch_op:
        batch_op.create_index('ix_measurement_audit_logs_survey_item_timestamp', ['survey_item_id', 'timestamp'], unique=False)


def downgrade():
    with op.batch_alter_table('measurement_audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_measurement_audit_logs_survey_item_timestamp')

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_engine_type'))
        batch_op.drop_index(batch_op.f('ix_jobs_customer_name'))
        batch_op.drop_index(batch_op.f('ix_jobs_serial_number'))
