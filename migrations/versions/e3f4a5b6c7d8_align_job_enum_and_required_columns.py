"""Align the migrated job enum and required columns with the existing models.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7

Do not manufacture slugs or historical upload timestamps. Existing nulls require
manual review before upgrading. No records or enum values are removed.
"""

from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    required = (
        ("organizations", "slug", sa.String(length=64)),
        ("job_costing_uploads", "uploaded_at", sa.DateTime()),
    )
    # Validate both columns before any DDL, including on SQLite where a batch
    # table rebuild does not provide PostgreSQL's transactional DDL guarantees.
    for table, column, _ in required:
        missing = bind.execute(sa.text(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
        )).scalar_one()
        if missing:
            raise RuntimeError(
                f"Migration aborted: {table}.{column} has {missing} NULL row(s); "
                "manual data review is required"
            )

    inspector = sa.inspect(bind)
    pending = [
        (table, column, existing_type) for table, column, existing_type in required
        if next(item for item in inspector.get_columns(table) if item["name"] == column)["nullable"]
    ]
    # SQLite batch alteration rebuilds parent tables. With FK enforcement on,
    # dropping the original parent can cascade-delete children. Never toggle
    # enforcement here or risk existing records; require a reviewed SQLite plan.
    if (bind.dialect.name == "sqlite" and pending
            and bind.execute(sa.text("PRAGMA foreign_keys")).scalar_one()):
        raise RuntimeError(
            "SQLite parent-table rebuild with foreign_keys enabled is unsafe; "
            "manual migration review is required"
        )

    if bind.dialect.name == "postgresql":
        # Do not use HOLD in DML/defaults until the enclosing migration commits.
        op.execute("ALTER TYPE jobstatusenum ADD VALUE IF NOT EXISTS 'HOLD'")

    for table, column, existing_type in pending:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, existing_type=existing_type, nullable=False)


def downgrade():
    raise RuntimeError(
        "Automatic downgrade cannot safely remove HOLD from existing job statuses; "
        "manual review is required"
    )
