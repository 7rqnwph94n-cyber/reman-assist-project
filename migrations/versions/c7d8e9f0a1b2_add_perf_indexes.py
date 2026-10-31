"""Add performance indexes for survey and parts

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-01-13 14:05:00
"""

from alembic import op


revision = "c7d8e9f0a1b2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_survey_items_job_decision",
        "survey_items",
        ["job_id", "decision"],
    )
    op.create_index(
        "ix_survey_items_job_measurement",
        "survey_items",
        ["job_id", "requires_measurement", "measurement_result"],
    )
    op.create_index(
        "ix_part_requirements_job_status",
        "part_requirements",
        ["job_id", "stock_status"],
    )
    op.create_index(
        "ix_part_requirements_job_approved",
        "part_requirements",
        ["job_id", "approved"],
    )


def downgrade():
    op.drop_index("ix_part_requirements_job_approved", table_name="part_requirements")
    op.drop_index("ix_part_requirements_job_status", table_name="part_requirements")
    op.drop_index("ix_survey_items_job_measurement", table_name="survey_items")
    op.drop_index("ix_survey_items_job_decision", table_name="survey_items")
