"""Add job versioning, attachment metadata, and performance indexes

Revision ID: ee4d7c2a9b10
Revises: 1a2b3c4d5e6f
Create Date: 2025-12-10
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ee4d7c2a9b10"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("survey_version", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("parts_version", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("survey_version", server_default=None)
        batch_op.alter_column("parts_version", server_default=None)

    with op.batch_alter_table("attachments") as batch_op:
        batch_op.add_column(sa.Column("original_filename", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("uploaded_by_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_attachments_uploaded_by_id_users", "users", ["uploaded_by_id"], ["id"])

    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_index("ix_jobs_updated_at", "jobs", ["updated_at"])
    op.create_index("ix_jobs_template_id", "jobs", ["template_id"])
    op.create_index("ix_jobs_assigned_to_id", "jobs", ["assigned_to_id"])

    op.create_index("ix_survey_items_job_id", "survey_items", ["job_id"])
    op.create_index("ix_survey_items_section", "survey_items", ["section"])
    op.create_index("ix_survey_items_pos", "survey_items", ["pos"])

    op.create_index("ix_part_requirements_job_id", "part_requirements", ["job_id"])
    op.create_index("ix_part_requirements_section", "part_requirements", ["section"])
    op.create_index("ix_part_requirements_pos", "part_requirements", ["pos"])
    op.create_index("ix_part_requirements_stock_status", "part_requirements", ["stock_status"])
    op.create_index("ix_part_requirements_created_at", "part_requirements", ["created_at"])
    op.create_index("ix_part_requirements_updated_at", "part_requirements", ["updated_at"])

    op.create_index("ix_attachments_job_id", "attachments", ["job_id"])

    op.create_index("ix_pick_lists_job_id", "pick_lists", ["job_id"])
    op.create_index("ix_pick_lists_status", "pick_lists", ["status"])

    op.create_index("ix_pick_list_items_pick_list_id", "pick_list_items", ["pick_list_id"])

    op.create_index("ix_audit_logs_job_id", "audit_logs", ["job_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_index("ix_nonconformances_job_id", "nonconformances", ["job_id"])
    op.create_index("ix_nonconformances_status", "nonconformances", ["status"])
    op.create_index("ix_nonconformances_created_at", "nonconformances", ["created_at"])
    op.create_index("ix_nonconformances_updated_at", "nonconformances", ["updated_at"])


def downgrade():
    op.drop_index("ix_nonconformances_updated_at", table_name="nonconformances")
    op.drop_index("ix_nonconformances_created_at", table_name="nonconformances")
    op.drop_index("ix_nonconformances_status", table_name="nonconformances")
    op.drop_index("ix_nonconformances_job_id", table_name="nonconformances")

    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_job_id", table_name="audit_logs")

    op.drop_index("ix_pick_list_items_pick_list_id", table_name="pick_list_items")

    op.drop_index("ix_pick_lists_status", table_name="pick_lists")
    op.drop_index("ix_pick_lists_job_id", table_name="pick_lists")

    op.drop_index("ix_attachments_job_id", table_name="attachments")

    op.drop_index("ix_part_requirements_updated_at", table_name="part_requirements")
    op.drop_index("ix_part_requirements_created_at", table_name="part_requirements")
    op.drop_index("ix_part_requirements_stock_status", table_name="part_requirements")
    op.drop_index("ix_part_requirements_pos", table_name="part_requirements")
    op.drop_index("ix_part_requirements_section", table_name="part_requirements")
    op.drop_index("ix_part_requirements_job_id", table_name="part_requirements")

    op.drop_index("ix_survey_items_pos", table_name="survey_items")
    op.drop_index("ix_survey_items_section", table_name="survey_items")
    op.drop_index("ix_survey_items_job_id", table_name="survey_items")

    op.drop_index("ix_jobs_assigned_to_id", table_name="jobs")
    op.drop_index("ix_jobs_template_id", table_name="jobs")
    op.drop_index("ix_jobs_updated_at", table_name="jobs")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")

    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_constraint("fk_attachments_uploaded_by_id_users", type_="foreignkey")
        batch_op.drop_column("uploaded_by_id")
        batch_op.drop_column("original_filename")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("parts_version")
        batch_op.drop_column("survey_version")
