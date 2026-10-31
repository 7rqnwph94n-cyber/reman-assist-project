"""hard multitenancy org slug

Revision ID: a1b2c3d4e5f6
Revises: 9b1c2d3e4f5g
Create Date: 2026-01-27 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone
import re


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '9b1c2d3e4f5g'
branch_labels = None
depends_on = None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip()).strip("-").lower()
    return slug or "org"


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

    if 'organizations' not in existing_tables:
        op.create_table(
            'organizations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('slug', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
            sa.UniqueConstraint('slug'),
        )
        with op.batch_alter_table('organizations', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_organizations_created_at'), ['created_at'], unique=False)
            batch_op.create_index(batch_op.f('ix_organizations_slug'), ['slug'], unique=True)
    else:
        if not has_column('organizations', 'slug'):
            with op.batch_alter_table('organizations', schema=None) as batch_op:
                batch_op.add_column(sa.Column('slug', sa.String(length=64), nullable=True))
        if not has_index('organizations', 'ix_organizations_slug'):
            with op.batch_alter_table('organizations', schema=None) as batch_op:
                batch_op.create_index(batch_op.f('ix_organizations_slug'), ['slug'], unique=True)

    for table_name, fk_name in (
        ('users', 'fk_users_organization_id'),
        ('jobs', 'fk_jobs_organization_id'),
        ('templates', 'fk_templates_organization_id'),
        ('template_items', 'fk_template_items_organization_id'),
    ):
        if table_name in existing_tables and not has_column(table_name, 'organization_id'):
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))

        if table_name in existing_tables and not has_index(table_name, f'ix_{table_name}_organization_id'):
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.create_index(
                    batch_op.f(f'ix_{table_name}_organization_id'),
                    ['organization_id'],
                    unique=False,
                )

        if table_name in existing_tables and not has_fk(table_name, fk_name):
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.create_foreign_key(
                    fk_name,
                    'organizations',
                    ['organization_id'],
                    ['id'],
                    ondelete='CASCADE',
                )

    org_table = sa.table(
        'organizations',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('slug', sa.String),
        sa.column('created_at', sa.DateTime),
    )

    org_name = "Global Reman"
    org_slug = "global-reman"
    org_id = bind.execute(sa.select(org_table.c.id).where(org_table.c.slug == org_slug)).scalar_one_or_none()
    if org_id is None:
        org_id = bind.execute(sa.select(org_table.c.id).where(org_table.c.name == org_name)).scalar_one_or_none()
        if org_id is None:
            now = datetime.now(timezone.utc)
            bind.execute(org_table.insert().values(name=org_name, slug=org_slug, created_at=now))
            org_id = bind.execute(sa.select(org_table.c.id).where(org_table.c.slug == org_slug)).scalar_one()
        else:
            bind.execute(
                sa.update(org_table).where(org_table.c.id == org_id).values(slug=org_slug)
            )

    existing = bind.execute(sa.select(org_table.c.id, org_table.c.name, org_table.c.slug)).all()
    used_slugs = {row.slug for row in existing if row.slug}
    for row in existing:
        if row.slug:
            continue
        base = _slugify(row.name)
        candidate = base
        if candidate in used_slugs:
            candidate = f"{base}-{row.id}"
        used_slugs.add(candidate)
        bind.execute(
            sa.update(org_table).where(org_table.c.id == row.id).values(slug=candidate)
        )

    if 'users' in existing_tables:
        bind.execute(
            sa.text("UPDATE users SET organization_id = :org_id WHERE organization_id IS NULL"),
            {"org_id": org_id},
        )
    if 'jobs' in existing_tables:
        bind.execute(
            sa.text("UPDATE jobs SET organization_id = :org_id WHERE organization_id IS NULL"),
            {"org_id": org_id},
        )
    if 'templates' in existing_tables:
        bind.execute(
            sa.text("UPDATE templates SET organization_id = :org_id WHERE organization_id IS NULL"),
            {"org_id": org_id},
        )
    if 'template_items' in existing_tables:
        bind.execute(
            sa.text(
                "UPDATE template_items SET organization_id = (SELECT organization_id FROM templates WHERE templates.id = template_items.template_id) "
                "WHERE organization_id IS NULL"
            )
        )
        bind.execute(
            sa.text("UPDATE template_items SET organization_id = :org_id WHERE organization_id IS NULL"),
            {"org_id": org_id},
        )

    for table_name in ('users', 'jobs', 'templates', 'template_items'):
        if table_name in existing_tables and has_column(table_name, 'organization_id'):
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.alter_column('organization_id', existing_type=sa.Integer(), nullable=False)

    if 'organizations' in existing_tables and has_column('organizations', 'slug'):
        with op.batch_alter_table('organizations', schema=None) as batch_op:
            batch_op.alter_column('slug', existing_type=sa.String(length=64), nullable=False)


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
        if batch_op.impl.dialect.name == 'sqlite':
            pass
        else:
            batch_op.drop_index(batch_op.f('ix_organizations_slug'))
        batch_op.drop_column('slug')
