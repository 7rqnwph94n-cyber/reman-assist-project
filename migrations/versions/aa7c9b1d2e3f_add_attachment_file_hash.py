"""add attachment file hash

Revision ID: aa7c9b1d2e3f
Revises: ca2e176c395f
Create Date: 2026-01-29 20:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa7c9b1d2e3f'
down_revision = 'ca2e176c395f'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('file_hash', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_attachments_file_hash', ['file_hash'], unique=False)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            DELETE FROM attachments a
            USING attachments b
            WHERE a.id > b.id
              AND a.job_id = b.job_id
              AND a.file_hash IS NOT NULL
              AND a.file_hash = b.file_hash;
            """
        )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("attachments", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_attachments_job_file_hash",
                ["job_id", "file_hash"],
            )
    else:
        op.create_unique_constraint(
            "uq_attachments_job_file_hash",
            "attachments",
            ["job_id", "file_hash"],
        )


def downgrade():
    op.drop_constraint('uq_attachments_job_file_hash', 'attachments', type_='unique')
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.drop_index('ix_attachments_file_hash')
        batch_op.drop_column('file_hash')
