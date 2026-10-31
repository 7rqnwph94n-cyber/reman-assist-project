"""add_app_logs

Revision ID: 7c1d2e3f4a5b
Revises: 6f2c1a0b9d7e
Create Date: 2026-01-27 14:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c1d2e3f4a5b'
down_revision = '6f2c1a0b9d7e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('level', sa.String(length=32), nullable=False, server_default='critical'),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('app_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_app_logs_job_id'), ['job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_app_logs_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_app_logs_request_id'), ['request_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_app_logs_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('app_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_app_logs_created_at'))
        batch_op.drop_index(batch_op.f('ix_app_logs_request_id'))
        batch_op.drop_index(batch_op.f('ix_app_logs_user_id'))
        batch_op.drop_index(batch_op.f('ix_app_logs_job_id'))

    op.drop_table('app_logs')
