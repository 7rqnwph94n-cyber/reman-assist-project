"""drop_nonconformances

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2025-01-18 21:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5e6f7a8b9c0d"
down_revision = "4d5e6f7a8b9c"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("nonconformances")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS nonconformancedecisionenum")
        op.execute("DROP TYPE IF EXISTS nonconformancestatusenum")


def downgrade():
    op.create_table(
        "nonconformances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("survey_item_id", sa.Integer(), nullable=True),
        sa.Column("part_requirement_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("OPEN", "UNDER_REVIEW", "CLOSED", name="nonconformancestatusenum"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column(
            "decision",
            sa.Enum(
                "ACCEPT_AS_IS",
                "SCRAP",
                "REWORK",
                "REPLACE",
                "CONCESSION",
                name="nonconformancedecisionenum",
            ),
            nullable=True,
        ),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["part_requirement_id"], ["part_requirements.id"]),
        sa.ForeignKeyConstraint(["survey_item_id"], ["survey_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
