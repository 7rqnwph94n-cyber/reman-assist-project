"""Add job costing uploads and link to costing sheets.

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-02-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "4d5e6f7a8b9c"
down_revision = "3c4d5e6f7a8b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_costing_uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("sheet_name", sa.String(length=128), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("job_id", "version", name="uq_job_costing_uploads_job_version"),
    )
    op.create_index("ix_job_costing_uploads_job_id", "job_costing_uploads", ["job_id"])

    with op.batch_alter_table("costing_sheets") as batch_op:
        batch_op.add_column(sa.Column("job_costing_upload_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_costing_sheets_job_costing_upload",
            "job_costing_uploads",
            ["job_costing_upload_id"],
            ["id"],
        )

    with op.batch_alter_table("job_costing_uploads") as batch_op:
        batch_op.alter_column("version", server_default=None)


def downgrade():
    with op.batch_alter_table("costing_sheets") as batch_op:
        batch_op.drop_constraint("fk_costing_sheets_job_costing_upload", type_="foreignkey")
        batch_op.drop_column("job_costing_upload_id")

    op.drop_index("ix_job_costing_uploads_job_id", table_name="job_costing_uploads")
    op.drop_table("job_costing_uploads")
