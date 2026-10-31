"""Add indexes for pick list and job log timestamps.

Revision ID: 3c4d5e6f7a8b
Revises: 2b7a9c1e5d10
Create Date: 2026-01-14 10:00:00.000000
"""

from alembic import op


revision = "3c4d5e6f7a8b"
down_revision = "2b7a9c1e5d10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_pick_lists_created_at", "pick_lists", ["created_at"])
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])
    op.create_index("ix_job_logs_timestamp", "job_logs", ["timestamp"])


def downgrade():
    op.drop_index("ix_job_logs_timestamp", table_name="job_logs")
    op.drop_index("ix_job_logs_job_id", table_name="job_logs")
    op.drop_index("ix_pick_lists_created_at", table_name="pick_lists")
