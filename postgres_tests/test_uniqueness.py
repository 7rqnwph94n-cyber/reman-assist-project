"""Real PostgreSQL enforcement checks; mandatory in the dedicated CI job."""

from uuid import uuid4

import pytest
import sqlalchemy as sa

from models import db


@pytest.mark.parametrize("table_name, key, constraint", [
    ("templates", "name", "uq_templates_org_name"),
    ("jobs", "job_number", "uq_jobs_org_job_number"),
    ("jobs", "job_pack_id", "uq_jobs_org_job_pack_id"),
])
def test_unique_keys_allow_other_tenants_and_reject_same_tenant_duplicates(postgres_app, table_name, key, constraint):
    token = uuid4().hex[:12]
    with postgres_app.app_context(), db.engine.connect() as connection:
        assert connection.dialect.name == "postgresql"
        transaction = connection.begin()
        try:
            organizations = db.metadata.tables["organizations"]
            org_ids = [connection.execute(organizations.insert().values(
                name=f"Unique {label} {token}", slug=f"unique-{label}-{token}",
            ).returning(organizations.c.id)).scalar_one() for label in ("owner", "other")]
            table = db.metadata.tables[table_name]
            values = {"name": f"shared-{token}"} if table_name == "templates" else {
                "job_number": f"shared-job-{token}", "job_pack_id": f"shared-pack-{token}",
            }
            ids = [connection.execute(table.insert().values(
                organization_id=org_id, **values,
            ).returning(table.c.id)).scalar_one() for org_id in org_ids]
            duplicate = dict(values)
            if table_name == "jobs":
                other_key = "job_pack_id" if key == "job_number" else "job_number"
                duplicate[other_key] = f"different-{token}"
            with pytest.raises(sa.exc.IntegrityError) as error:
                with connection.begin_nested():
                    connection.execute(table.insert().values(organization_id=org_ids[0], **duplicate))
            assert error.value.orig.pgcode == "23505"
            assert error.value.orig.diag.constraint_name == constraint
            rows = connection.execute(sa.select(table.c.id, table.c.organization_id, table.c[key]).where(
                table.c.organization_id.in_(org_ids),
            ).order_by(table.c.id)).all()
            assert rows == [(ids[0], org_ids[0], values[key]), (ids[1], org_ids[1], values[key])]
        finally:
            transaction.rollback()
