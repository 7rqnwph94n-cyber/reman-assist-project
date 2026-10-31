"""Add job_id indexes for core tables

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-01-13 16:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def _maybe_create_index(bind, name, table, cols):
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes(table)}
    if name in existing:
        return
    op.create_index(name, table, cols)


def _maybe_drop_index(bind, name, table):
    existing = {idx["name"] for idx in sa.inspect(bind).get_indexes(table)}
    if name not in existing:
        return
    op.drop_index(name, table_name=table)


def upgrade():
    bind = op.get_bind()
    _maybe_create_index(bind, "ix_attachments_job_id", "attachments", ["job_id"])
    _maybe_create_index(bind, "ix_part_requirements_job_id", "part_requirements", ["job_id"])
    _maybe_create_index(bind, "ix_survey_items_job_id", "survey_items", ["job_id"])


def downgrade():
    bind = op.get_bind()
    _maybe_drop_index(bind, "ix_survey_items_job_id", "survey_items")
    _maybe_drop_index(bind, "ix_part_requirements_job_id", "part_requirements")
    _maybe_drop_index(bind, "ix_attachments_job_id", "attachments")
