"""Add the report revision table omitted from the original migration chain.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6

Existing deployed/model-created tables and their audit rows are left intact.
This additive repair cannot be automatically downgraded: the table may predate
this revision, and deleting report revision history would be unsafe.
"""

from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("job_report_revisions"):
        required = {"id", "job_id", "revision", "reason", "user_id", "created_at"}
        present = {column["name"] for column in inspector.get_columns("job_report_revisions")}
        if not required <= present:
            raise RuntimeError("Existing job_report_revisions is incomplete; manual schema review is required")
        return

    # Frozen schema snapshot: do not import application models into a migration.
    op.create_table(
        "job_report_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"],
                                name="job_report_revisions_job_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name="job_report_revisions_user_id_fkey"),
    )
    for column in ("job_id", "created_at"):
        op.create_index(f"ix_job_report_revisions_{column}", "job_report_revisions", [column])


def downgrade():
    raise RuntimeError("Automatic downgrade would risk existing report revision audit data; manual review is required")
