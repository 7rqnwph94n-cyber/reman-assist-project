"""enforce_job_pack_id

Revision ID: 6a7b8c9d0e1f
Revises: 5e6f7a8b9c0d
Create Date: 2025-01-18 22:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6a7b8c9d0e1f"
down_revision = "5e6f7a8b9c0d"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE jobs SET job_pack_id = job_number WHERE job_pack_id IS NULL OR job_pack_id = ''")

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column("job_pack_id", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_check_constraint("ck_jobs_job_pack_id_not_empty", "job_pack_id <> ''")


def downgrade():
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("ck_jobs_job_pack_id_not_empty", type_="check")
        batch_op.alter_column("job_pack_id", existing_type=sa.String(length=64), nullable=True)
