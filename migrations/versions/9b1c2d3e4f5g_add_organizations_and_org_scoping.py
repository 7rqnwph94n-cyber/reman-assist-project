"""add organizations and org scoping

Revision ID: 9b1c2d3e4f5g
Revises: 8a1b2c3d4e5f
Create Date: 2026-01-27 16:10:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = '9b1c2d3e4f5g'
down_revision = '8a1b2c3d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    def has_column(table_name, column_name):
        return column_name in {col["name"] for col in inspector.get_columns(table_name)}

    def has_index(table_name, index_name):
        return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}

    def has_fk(table_name, fk_name):
        return fk_name in {fk["name"] for fk in inspector.get_foreign_keys(table_name)}

    created_org_table = False
    if 'organizations' not in existing_tables:
        op.create_table(
            'organizations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
        )
        created_org_table = True
    if created_org_table or ('organizations' in existing_tables and not has_index('organizations', 'ix_organizations_created_at')):
        with op.batch_alter_table('organizations', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_organizations_created_at'), ['created_at'], unique=False)

    users_has_org = has_column('users', 'organization_id')
    if not users_has_org:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        users_has_org = True
    if not has_index('users', 'ix_users_organization_id'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_users_organization_id'), ['organization_id'], unique=False)
    if not has_fk('users', 'fk_users_organization_id'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.create_foreign_key(
                'fk_users_organization_id',
                'organizations',
                ['organization_id'],
                ['id'],
                ondelete='CASCADE',
            )

    jobs_has_org = has_column('jobs', 'organization_id')
    if not jobs_has_org:
        with op.batch_alter_table('jobs', schema=None) as batch_op:
            batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        jobs_has_org = True
    if not has_index('jobs', 'ix_jobs_organization_id'):
        with op.batch_alter_table('jobs', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_jobs_organization_id'), ['organization_id'], unique=False)
    if not has_fk('jobs', 'fk_jobs_organization_id'):
        with op.batch_alter_table('jobs', schema=None) as batch_op:
            batch_op.create_foreign_key(
                'fk_jobs_organization_id',
                'organizations',
                ['organization_id'],
                ['id'],
                ondelete='CASCADE',
            )

    templates_has_org = has_column('templates', 'organization_id')
    if not templates_has_org:
        with op.batch_alter_table('templates', schema=None) as batch_op:
            batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        templates_has_org = True
    if not has_index('templates', 'ix_templates_organization_id'):
        with op.batch_alter_table('templates', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_templates_organization_id'), ['organization_id'], unique=False)
    if not has_fk('templates', 'fk_templates_organization_id'):
        with op.batch_alter_table('templates', schema=None) as batch_op:
            batch_op.create_foreign_key(
                'fk_templates_organization_id',
                'organizations',
                ['organization_id'],
                ['id'],
                ondelete='CASCADE',
            )

    template_items_has_org = has_column('template_items', 'organization_id')
    if not template_items_has_org:
        with op.batch_alter_table('template_items', schema=None) as batch_op:
            batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        template_items_has_org = True
    if not has_index('template_items', 'ix_template_items_organization_id'):
        with op.batch_alter_table('template_items', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_template_items_organization_id'), ['organization_id'], unique=False)
    if not has_fk('template_items', 'fk_template_items_organization_id'):
        with op.batch_alter_table('template_items', schema=None) as batch_op:
            batch_op.create_foreign_key(
                'fk_template_items_organization_id',
                'organizations',
                ['organization_id'],
                ['id'],
                ondelete='CASCADE',
            )

    org_name = "Global Reman"
    now = datetime.now(timezone.utc)

    org_table = sa.table(
        'organizations',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('created_at', sa.DateTime),
    )

    org_id = bind.execute(sa.select(org_table.c.id).where(org_table.c.name == org_name)).scalar_one_or_none()
    if org_id is None:
        bind.execute(org_table.insert().values(name=org_name, created_at=now))
        org_id = bind.execute(sa.select(org_table.c.id).where(org_table.c.name == org_name)).scalar_one()

    if users_has_org:
        bind.execute(sa.text("UPDATE users SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": org_id})
    if jobs_has_org:
        bind.execute(sa.text("UPDATE jobs SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": org_id})
    if templates_has_org:
        bind.execute(sa.text("UPDATE templates SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": org_id})
    if template_items_has_org:
        bind.execute(sa.text(
            "UPDATE template_items SET organization_id = (SELECT organization_id FROM templates WHERE templates.id = template_items.template_id) "
            "WHERE organization_id IS NULL"
        ))
        bind.execute(sa.text("UPDATE template_items SET organization_id = :org_id WHERE organization_id IS NULL"), {"org_id": org_id})


def downgrade():
    with op.batch_alter_table('template_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_template_items_organization_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_template_items_organization_id'))
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_constraint('fk_templates_organization_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_templates_organization_id'))
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_constraint('fk_jobs_organization_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_jobs_organization_id'))
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_organization_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_users_organization_id'))
        batch_op.drop_column('organization_id')

    with op.batch_alter_table('organizations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organizations_created_at'))

    op.drop_table('organizations')
