"""Add QuickBooks integration tables and columns

Revision ID: bb8c9d0e1f2a
Revises: aa7c9b1d2e3f
Create Date: 2026-02-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'bb8c9d0e1f2a'
down_revision = 'aa7c9b1d2e3f'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    is_sqlite = bind.dialect.name == "sqlite"

    # Create enums
    if is_postgres:
        qb_env_enum = postgresql.ENUM('sandbox', 'production', name='qbenvironmentenum', create_type=False)
        qb_sync_status_enum = postgresql.ENUM('never_synced', 'synced', 'failed', 'needs_update', name='qbsyncstatusenum', create_type=False)
        qb_sync_type_enum = postgresql.ENUM('invoice', 'expense', 'customer', 'vendor', name='qbsynctypeenum', create_type=False)
        for enum_type in [qb_env_enum, qb_sync_status_enum, qb_sync_type_enum]:
            enum_type.create(bind, checkfirst=True)
            enum_type._create_events = False
        is_active_default = sa.text("true")
        auto_create_default = sa.text("true")
    else:
        qb_env_enum = sa.Enum('sandbox', 'production', name='qbenvironmentenum')
        qb_sync_status_enum = sa.Enum('never_synced', 'synced', 'failed', 'needs_update', name='qbsyncstatusenum')
        qb_sync_type_enum = sa.Enum('invoice', 'expense', 'customer', 'vendor', name='qbsynctypeenum')
        qb_env_enum.create(bind, checkfirst=True)
        qb_sync_status_enum.create(bind, checkfirst=True)
        qb_sync_type_enum.create(bind, checkfirst=True)
        is_active_default = sa.text("1")
        auto_create_default = sa.text("1")

    # Create quickbooks_connections table
    op.create_table(
        'quickbooks_connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('realm_id', sa.String(128), nullable=False),
        sa.Column('company_name', sa.String(255), nullable=True),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(), nullable=False),
        sa.Column('refresh_token_expires_at', sa.DateTime(), nullable=True),
        sa.Column('environment', qb_env_enum, nullable=False, server_default='sandbox'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=is_active_default),
        sa.Column('default_income_account_id', sa.String(64), nullable=True),
        sa.Column('default_expense_account_id', sa.String(64), nullable=True),
        sa.Column('auto_create_customers', sa.Boolean(), nullable=False, server_default=auto_create_default),
        sa.Column('invoice_prefix', sa.String(32), nullable=True),
        sa.Column('connected_by_id', sa.Integer(), nullable=True),
        sa.Column('connected_at', sa.DateTime(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('last_test_at', sa.DateTime(), nullable=True),
        sa.Column('last_test_status', sa.String(32), nullable=True),
        sa.Column('last_test_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['connected_by_id'], ['users.id']),
        sa.UniqueConstraint('organization_id', name='uq_qb_conn_org'),
    )
    op.create_index('ix_quickbooks_connections_organization_id', 'quickbooks_connections', ['organization_id'])

    # Create quickbooks_sync_logs table
    op.create_table(
        'quickbooks_sync_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('sync_type', qb_sync_type_enum, nullable=False),
        sa.Column('entity_type', sa.String(32), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('qb_id', sa.String(128), nullable=True),
        sa.Column('qb_doc_number', sa.String(64), nullable=True),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('synced_by_id', sa.Integer(), nullable=True),
        sa.Column('request_payload', sa.JSON(), nullable=True),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['synced_by_id'], ['users.id']),
    )
    op.create_index('ix_quickbooks_sync_logs_organization_id', 'quickbooks_sync_logs', ['organization_id'])
    op.create_index('ix_quickbooks_sync_logs_entity_id', 'quickbooks_sync_logs', ['entity_id'])
    op.create_index('ix_quickbooks_sync_logs_synced_at', 'quickbooks_sync_logs', ['synced_at'])

    # Create quickbooks_customer_maps table
    op.create_table(
        'quickbooks_customer_maps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('customer_name', sa.String(255), nullable=False),
        sa.Column('customer_name_normalized', sa.String(255), nullable=False),
        sa.Column('qb_customer_id', sa.String(64), nullable=False),
        sa.Column('qb_display_name', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('organization_id', 'customer_name_normalized', name='uq_qb_customer_org_name'),
    )
    op.create_index('ix_quickbooks_customer_maps_normalized', 'quickbooks_customer_maps', ['customer_name_normalized'])

    # Add QB columns to jobs table
    op.add_column('jobs', sa.Column('qb_invoice_id', sa.String(128), nullable=True))
    op.add_column('jobs', sa.Column('qb_invoice_number', sa.String(64), nullable=True))
    op.add_column('jobs', sa.Column('qb_invoice_url', sa.String(512), nullable=True))
    # SQLite cannot add CHECK-backed enum constraints via ALTER TABLE; use a plain string.
    qb_sync_status_type_for_jobs = sa.String(32) if is_sqlite else qb_sync_status_enum
    op.add_column(
        'jobs',
        sa.Column('qb_sync_status', qb_sync_status_type_for_jobs, nullable=True, server_default='never_synced')
    )
    op.add_column('jobs', sa.Column('qb_last_sync_at', sa.DateTime(), nullable=True))
    op.add_column('jobs', sa.Column('qb_sync_error', sa.Text(), nullable=True))
    op.create_index('ix_jobs_qb_invoice_id', 'jobs', ['qb_invoice_id'])

    # Add QB columns to part_requirements table
    op.add_column('part_requirements', sa.Column('qb_expense_id', sa.String(128), nullable=True))
    op.add_column('part_requirements', sa.Column('qb_bill_id', sa.String(128), nullable=True))
    op.add_column('part_requirements', sa.Column('qb_last_sync_at', sa.DateTime(), nullable=True))
    op.create_index('ix_part_requirements_qb_expense_id', 'part_requirements', ['qb_expense_id'])


def downgrade():
    # Remove indexes
    op.drop_index('ix_part_requirements_qb_expense_id', 'part_requirements')
    op.drop_index('ix_jobs_qb_invoice_id', 'jobs')

    # Remove columns from part_requirements
    op.drop_column('part_requirements', 'qb_last_sync_at')
    op.drop_column('part_requirements', 'qb_bill_id')
    op.drop_column('part_requirements', 'qb_expense_id')

    # Remove columns from jobs
    op.drop_column('jobs', 'qb_sync_error')
    op.drop_column('jobs', 'qb_last_sync_at')
    op.drop_column('jobs', 'qb_sync_status')
    op.drop_column('jobs', 'qb_invoice_url')
    op.drop_column('jobs', 'qb_invoice_number')
    op.drop_column('jobs', 'qb_invoice_id')

    # Drop indexes
    op.drop_index('ix_quickbooks_customer_maps_normalized', 'quickbooks_customer_maps')
    op.drop_index('ix_quickbooks_sync_logs_synced_at', 'quickbooks_sync_logs')
    op.drop_index('ix_quickbooks_sync_logs_entity_id', 'quickbooks_sync_logs')
    op.drop_index('ix_quickbooks_sync_logs_organization_id', 'quickbooks_sync_logs')
    op.drop_index('ix_quickbooks_connections_organization_id', 'quickbooks_connections')

    # Drop tables
    op.drop_table('quickbooks_customer_maps')
    op.drop_table('quickbooks_sync_logs')
    op.drop_table('quickbooks_connections')

    # Drop enums
    bind = op.get_bind()
    for enum_name in ['qbsynctypeenum', 'qbsyncstatusenum', 'qbenvironmentenum']:
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
