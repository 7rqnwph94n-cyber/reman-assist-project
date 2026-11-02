"""Uniqueness verification, real disposable SQLite DDL, and offline PG SQL."""

import io
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask_migrate import upgrade
import pytest
import sqlalchemy as sa

from models import db
from scripts import ci_postgres
from scripts.migration_check import migration_script
from tests.test_fk_cascade_migration import MIGRATIONS, migration_app


REVISION = "f4a5b6c7d8e9"

EXPECTED_KEYS = {
    "engine_types": {("code",)}, "organizations": {("name",), ("slug",)},
    "parts": {("part_no",)}, "users": {("username",)},
    "templates": {("organization_id", "name")},
    "jobs": {("organization_id", "job_number"), ("organization_id", "job_pack_id")},
    "quickbooks_connections": {("organization_id",)},
    "quickbooks_customer_maps": {("organization_id", "customer_name_normalized")},
    "template_wizard_states": {("template_id",)}, "attachments": {("job_id", "file_hash")},
    "job_costing_uploads": {("job_id", "version")}, "pre_survey_results": {("job_id",)},
    "store_items": {("organization_id", "barcode"), ("template_item_id",)},
    "template_measurement_specs": {("template_item_id", "instance_index")},
    "costing_sheets": {("job_id",)},
}


def test_model_uniqueness_matches_the_independent_integrity_inventory():
    actual = {}
    for table in db.metadata.tables.values():
        keys = {frozenset(column.name for column in rule.columns)
                for rule in table.constraints if isinstance(rule, sa.UniqueConstraint)}
        keys.update(frozenset(column.name for column in index.columns) for index in table.indexes if index.unique)
        if keys:
            actual[table.name] = keys
    assert actual == {table: {frozenset(key) for key in keys} for table, keys in EXPECTED_KEYS.items()}


@pytest.mark.parametrize("table_name,key", [
    (table, key) for table, keys in EXPECTED_KEYS.items() for key in sorted(keys)
])
def test_each_of_the_18_required_rules_is_rejected_when_missing(table_name, key):
    inspector = CatalogInspector(constraints=[
        {"name": "other_rule", "column_names": list(other)}
        for other in EXPECTED_KEYS[table_name] if other != key
    ])
    with pytest.raises(RuntimeError, match=f"Missing unique constraints on {table_name}"):
        ci_postgres.verify_table_uniqueness(inspector, db.metadata.tables[table_name])


def metadata_for(table_name="templates", as_index=False):
    metadata = sa.MetaData()
    table = sa.Table(table_name, metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("organization_id", sa.Integer, nullable=False),
                     sa.Column("name", sa.String(128), nullable=False))
    if as_index:
        sa.Index("model_unique", table.c.organization_id, table.c.name, unique=True)
    else:
        table.append_constraint(sa.UniqueConstraint("organization_id", "name"))
    return metadata, table


class CatalogConnection:
    def __init__(self, invalid=()):
        self.invalid = list(invalid)

    def execute(self, statement):
        sql = str(statement)
        assert "pg_catalog.pg_index" in sql
        assert all(flag in sql for flag in ("indisvalid", "indisready", "indislive"))
        assert "n.nspname = 'public'" in sql
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: self.invalid))


class CatalogInspector:
    def __init__(self, constraints=(), indexes=()):
        self.constraints, self.indexes = list(constraints), list(indexes)

    def get_table_names(self, **kwargs):
        return ["templates"]

    def get_columns(self, *args, **kwargs):
        return [{"name": name, "type": sa.Integer() if name != "name" else sa.String(128), "nullable": False}
                for name in ("id", "organization_id", "name")]

    def get_pk_constraint(self, *args, **kwargs):
        return {"name": "templates_pkey", "constrained_columns": ["id"]}

    def get_foreign_keys(self, *args, **kwargs):
        return []

    def get_unique_constraints(self, *args, **kwargs):
        return self.constraints

    def get_indexes(self, *args, **kwargs):
        return self.indexes

    def get_check_constraints(self, *args, **kwargs):
        return []

    def get_sequence_names(self, **kwargs):
        return []

    get_view_names = get_sequence_names
    get_materialized_view_names = get_sequence_names
    get_enums = get_sequence_names


@pytest.mark.parametrize("constraints,indexes", [
    ([{"name": None, "column_names": ["organization_id", "name"]}], []),
    ([{"name": "arbitrary_name", "column_names": ["name", "organization_id"]}], []),
    ([], [{"name": "standalone", "column_names": ["name", "organization_id"], "unique": True}]),
    ([], [{"name": "covering", "column_names": ["organization_id", "name"], "unique": True,
           "include_columns": ["id"], "dialect_options": {"postgresql_include": ["id"]}}]),
    ([{"name": "backed", "column_names": ["organization_id", "name"]}],
     [{"name": "backed", "column_names": ["organization_id", "name"], "unique": True, "duplicates_constraint": "backed"}]),
])
@pytest.mark.parametrize("as_index", [False, True])
def test_fingerprint_accepts_equivalent_full_uniqueness(monkeypatch, constraints, indexes, as_index):
    metadata, _ = metadata_for(as_index=as_index)
    monkeypatch.setattr(ci_postgres, "inspect", lambda connection: CatalogInspector(constraints, indexes))
    assert len(ci_postgres.schema_fingerprint(CatalogConnection(), metadata)) == 64


@pytest.mark.parametrize("indexes", [
    [],
    [{"name": "not_unique", "column_names": ["organization_id", "name"], "unique": False}],
    [{"name": "wrong", "column_names": ["organization_id"], "unique": True}],
    [{"name": "extra_key", "column_names": ["organization_id", "name", "id"], "unique": True}],
    [{"name": "partial", "column_names": ["organization_id", "name"], "unique": True,
      "dialect_options": {"postgresql_where": "id > 5"}}],
    [{"name": "expression", "column_names": ["organization_id", None], "unique": True,
      "expressions": ["organization_id", "lower(name)"]}],
    [{"name": "legacy_global", "column_names": ["name"], "unique": True}],
])
def test_missing_or_incorrect_uniqueness_still_fails_the_gate(monkeypatch, indexes):
    metadata, _ = metadata_for()
    monkeypatch.setattr(ci_postgres, "inspect", lambda connection: CatalogInspector(indexes=indexes))
    with pytest.raises(RuntimeError, match=r"Missing unique constraints on templates:.*organization_id"):
        ci_postgres.schema_fingerprint(CatalogConnection(), metadata)


def test_adding_composite_without_removing_obsolete_global_rule_is_rejected(monkeypatch):
    metadata, _ = metadata_for()
    inspector = CatalogInspector(constraints=[
        {"name": "scoped", "column_names": ["organization_id", "name"]},
        {"name": "global", "column_names": ["name"]},
    ])
    monkeypatch.setattr(ci_postgres, "inspect", lambda connection: inspector)
    with pytest.raises(RuntimeError, match="Obsolete global uniqueness on templates"):
        ci_postgres.schema_fingerprint(CatalogConnection(), metadata)


def test_invalid_unique_index_is_rejected_before_schema_matching(monkeypatch):
    metadata, _ = metadata_for()
    monkeypatch.setattr(ci_postgres, "inspect", lambda connection: CatalogInspector())
    with pytest.raises(RuntimeError, match="Invalid or inactive.*templates.failed_build"):
        ci_postgres.schema_fingerprint(CatalogConnection([
            {"table_name": "templates", "index_name": "failed_build"},
        ]), metadata)


@pytest.mark.parametrize("nullable,nulls_not_distinct", [(True, False), (True, True), (False, True)])
def test_null_semantics_are_preserved_without_rejecting_equivalent_nonnull_keys(nullable, nulls_not_distinct):
    _, table = metadata_for()
    table.c.name.nullable = nullable
    inspector = CatalogInspector(indexes=[{
        "name": "unique_key", "column_names": ["organization_id", "name"], "unique": True,
        "dialect_options": {"postgresql_nulls_not_distinct": nulls_not_distinct},
    }])
    if nullable and nulls_not_distinct:
        with pytest.raises(RuntimeError, match="Unexpected NULLS NOT DISTINCT"):
            ci_postgres.verify_table_uniqueness(inspector, table)
    else:
        ci_postgres.verify_table_uniqueness(inspector, table)


def test_migration_refuses_invalid_target_indexes_before_inspection_or_ddl(monkeypatch):
    module = migration_script().get_revision(REVISION).module

    def execute(statement):
        assert "pg_catalog.pg_index" in str(statement)
        assert all(flag in str(statement) for flag in ("indisvalid", "indisready", "indislive"))
        return SimpleNamespace(scalar_one=lambda: 1)

    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=execute)
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: bind))
    with pytest.raises(RuntimeError, match="Invalid template/job unique indexes.*manual review"):
        module.upgrade()


@pytest.mark.parametrize("kind", ["partial", "expression"])
def test_unaudited_model_index_semantics_require_explicit_validation(kind):
    metadata, table = metadata_for()
    expression = sa.func.lower(table.c.name) if kind == "expression" else table.c.name
    options = {"postgresql_where": table.c.id > 5} if kind == "partial" else {}
    sa.Index("special_unique", expression, unique=True, **options)
    with pytest.raises(RuntimeError, match="requires explicit"):
        ci_postgres.verify_table_uniqueness(CatalogInspector(), table)


def run_repair(connection):
    with Operations.context(MigrationContext.configure(connection)):
        migration_script().get_revision(REVISION).module.upgrade()


@pytest.fixture
def migrated_connection(migration_app):
    upgrade(directory=MIGRATIONS, revision="e3f4a5b6c7d8")
    with db.engine.connect() as connection:
        yield connection


def seed_rows(connection):
    org = connection.execute(sa.text("SELECT id FROM organizations WHERE slug='global-reman'")).scalar_one()
    other = connection.execute(db.metadata.tables["organizations"].insert().values(name="Other org", slug="other-org")).inserted_primary_key[0]
    template = connection.execute(db.metadata.tables["templates"].insert().values(
        organization_id=org, name="Retained template")).inserted_primary_key[0]
    connection.execute(db.metadata.tables["template_items"].insert().values(organization_id=org, template_id=template, name="Retained child"))
    job = connection.execute(db.metadata.tables["jobs"].insert().values(
        organization_id=org, job_number="Retained job", job_pack_id="Retained pack", template_id=template)).inserted_primary_key[0]
    connection.execute(db.metadata.tables["survey_items"].insert().values(job_id=job, name="Retained survey"))
    connection.execute(db.metadata.tables["audit_logs"].insert().values(job_id=job, action="existing", message="Retain audit"))
    connection.execute(db.metadata.tables["job_report_revisions"].insert().values(job_id=job, revision=1, reason="Retain revision"))
    connection.commit()
    return org, other


def data_snapshot(connection):
    return {table.name: connection.execute(sa.select(table).order_by(*table.primary_key.columns)).all()
            for table in db.metadata.sorted_tables}


def schema_snapshot(connection):
    return connection.execute(sa.text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")).all()


def test_real_predecessor_reproduces_failure_and_forward_repair_preserves_all_rows(migrated_connection):
    connection = migrated_connection
    org, other = seed_rows(connection)
    for table in ("templates", "jobs"):
        with pytest.raises(RuntimeError, match=f"Missing unique constraints on {table}"):
            ci_postgres.verify_table_uniqueness(sa.inspect(connection), db.metadata.tables[table])
    before = data_snapshot(connection)
    run_repair(connection)
    assert data_snapshot(connection) == before
    # Audit EVERY model rule against the real migrated schema, not db.create_all.
    for table in db.metadata.sorted_tables:
        ci_postgres.verify_table_uniqueness(sa.inspect(connection), table)
    for table, columns in (("job_costing_uploads", {"job_id", "version"}),
                           ("template_measurement_specs", {"template_item_id", "instance_index"})):
        assert frozenset(columns) in ci_postgres.reflected_unique_column_sets(sa.inspect(connection), table)
    # Same identifiers across tenants must now work for all three repaired keys.
    connection.execute(db.metadata.tables["templates"].insert().values(organization_id=other, name="Retained template"))
    connection.execute(db.metadata.tables["jobs"].insert().values(
        organization_id=other, job_number="Retained job", job_pack_id="Retained pack"))
    for table, values in (
        ("templates", {"organization_id": org, "name": "Retained template"}),
        ("jobs", {"organization_id": org, "job_number": "Retained job", "job_pack_id": "Different pack"}),
        ("jobs", {"organization_id": org, "job_number": "Different job", "job_pack_id": "Retained pack"}),
    ):
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(db.metadata.tables[table].insert().values(**values))
    # No extra constraints/indexes or data changes on a repeat upgrade.
    after, schema = data_snapshot(connection), schema_snapshot(connection)
    run_repair(connection)
    assert data_snapshot(connection) == after and schema_snapshot(connection) == schema
    with pytest.raises(RuntimeError, match="cannot restore global uniqueness"):
        migration_script().get_revision(REVISION).module.downgrade()
    assert data_snapshot(connection) == after


def make_drifted_schema(connection):
    connection.execute(sa.text("CREATE TABLE templates (id INTEGER PRIMARY KEY, organization_id INTEGER, name TEXT)"))
    connection.execute(sa.text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, organization_id INTEGER, job_number TEXT, job_pack_id TEXT)"))
    connection.execute(sa.text("INSERT INTO templates VALUES (1, 1, 'private name')"))
    connection.execute(sa.text("INSERT INTO jobs VALUES (1, 1, 'private job', 'private pack')"))


@pytest.mark.parametrize("table,column,value", [
    ("templates", "name", "private name"), ("jobs", "job_number", "private job"),
    ("jobs", "job_pack_id", "private pack"), ("templates", "organization_id", None),
    ("jobs", "organization_id", None),
])
def test_duplicate_or_null_keys_fail_before_any_ddl_without_exposing_values(migration_app, table, column, value):
    with db.engine.begin() as connection:
        make_drifted_schema(connection)
        values = {"id": 2, "organization_id": 1}
        values.update({"name": "distinct"} if table == "templates" else {"job_number": "distinct", "job_pack_id": "distinct"})
        values[column] = value
        reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
        connection.execute(reflected.insert().values(**values))
        before = {name: connection.execute(sa.text(f"SELECT * FROM {name} ORDER BY id")).all() for name in ("templates", "jobs")}
        schema = schema_snapshot(connection)
        with pytest.raises(RuntimeError, match="manual data review") as error:
            run_repair(connection)
        assert "private" not in str(error.value)
        assert table in str(error.value)
        assert schema_snapshot(connection) == schema
        assert {name: connection.execute(sa.text(f"SELECT * FROM {name} ORDER BY id")).all() for name in before} == before


@pytest.mark.parametrize("legacy", [False, True])
def test_equivalent_indexes_are_reused_and_standalone_global_indexes_removed(migration_app, legacy):
    with db.engine.begin() as connection:
        make_drifted_schema(connection)
        for table, name, columns in (
            ("templates", "existing_scoped", "name, organization_id"),
            ("jobs", "existing_number", "job_number, organization_id"),
            ("jobs", "existing_pack", "job_pack_id, organization_id"),
        ):
            connection.execute(sa.text(f"CREATE UNIQUE INDEX {name} ON {table} ({columns})"))
        if legacy:
            for table, column in (("templates", "name"), ("jobs", "job_number"), ("jobs", "job_pack_id")):
                connection.execute(sa.text(f"CREATE UNIQUE INDEX old_{column} ON {table} ({column})"))
        before = schema_snapshot(connection)
        run_repair(connection)
        indexes = {index["name"] for table in ("templates", "jobs") for index in sa.inspect(connection).get_indexes(table)}
        assert indexes == {"existing_scoped", "existing_number", "existing_pack"}
        assert all(not sa.inspect(connection).get_unique_constraints(table) for table in ("templates", "jobs"))
        if not legacy:
            assert schema_snapshot(connection) == before


def test_parent_rebuild_with_enforced_foreign_keys_refuses_without_losing_children(migrated_connection):
    connection = migrated_connection
    seed_rows(connection)
    connection.execute(sa.text("PRAGMA foreign_keys=ON"))
    assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar_one() == 1
    before, schema = data_snapshot(connection), schema_snapshot(connection)
    with pytest.raises(RuntimeError, match="parent-table rebuild.*unsafe"):
        run_repair(connection)
    assert data_snapshot(connection) == before and schema_snapshot(connection) == schema
    assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar_one() == 1


@pytest.mark.parametrize("obstacle", ["name_conflict", "natural_key_reference"])
def test_legacy_schema_dependencies_refuse_before_any_ddl(migration_app, obstacle):
    with db.engine.begin() as connection:
        make_drifted_schema(connection)
        if obstacle == "name_conflict":
            connection.execute(sa.text("CREATE UNIQUE INDEX uq_templates_org_name ON templates(name)"))
        else:
            connection.execute(sa.text("CREATE UNIQUE INDEX legacy_template_name ON templates(name)"))
            connection.execute(sa.text("CREATE TABLE legacy_links (id INTEGER PRIMARY KEY, template_name TEXT REFERENCES templates(name))"))
            connection.execute(sa.text("INSERT INTO legacy_links VALUES (1, 'private name')"))
        schema = schema_snapshot(connection)
        before = connection.execute(sa.text("SELECT * FROM templates")).all()
        with pytest.raises(RuntimeError, match="manual schema review"):
            run_repair(connection)
        assert schema_snapshot(connection) == schema
        assert connection.execute(sa.text("SELECT * FROM templates")).all() == before
        if obstacle == "natural_key_reference":
            assert connection.execute(sa.text("SELECT template_name FROM legacy_links")).scalar_one() == "private name"


def test_actual_postgres_migration_sql_replaces_only_the_three_legacy_keys(migrated_connection, monkeypatch):
    connection = migrated_connection
    real = sa.inspect(connection)

    class PGNames:
        def get_unique_constraints(self, table):
            return [{**rule, "name": rule["name"] or f"{table}_{'_'.join(rule['column_names'])}_key"}
                    for rule in real.get_unique_constraints(table)]

        def get_indexes(self, table):
            return real.get_indexes(table)

        def get_table_names(self):
            return real.get_table_names()

        def get_foreign_keys(self, table):
            return real.get_foreign_keys(table)

    output = io.StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
    module = migration_script().get_revision(REVISION).module

    def execute(statement):
        if "pg_catalog.pg_index" in str(statement):
            return SimpleNamespace(scalar_one=lambda: 0)
        return connection.execute(statement)

    class Proxy:
        def get_bind(self):
            return SimpleNamespace(dialect=operations.get_bind().dialect, execute=execute)

        def __getattr__(self, name):
            return getattr(operations, name)

    monkeypatch.setattr(module, "op", Proxy())
    monkeypatch.setattr(module, "sa", SimpleNamespace(**{**vars(sa), "inspect": lambda bind: PGNames()}))
    module.upgrade()
    sql = [statement.strip() for statement in output.getvalue().split(";") if statement.strip()]
    assert set(sql) == {
        "ALTER TABLE templates ADD CONSTRAINT uq_templates_org_name UNIQUE (organization_id, name)",
        "ALTER TABLE templates DROP CONSTRAINT templates_name_key",
        "ALTER TABLE jobs ADD CONSTRAINT uq_jobs_org_job_number UNIQUE (organization_id, job_number)",
        "ALTER TABLE jobs ADD CONSTRAINT uq_jobs_org_job_pack_id UNIQUE (organization_id, job_pack_id)",
        "ALTER TABLE jobs DROP CONSTRAINT jobs_job_number_key",
        "ALTER TABLE jobs DROP CONSTRAINT uq_jobs_job_pack_id",
    }
    for table in ("templates", "jobs"):
        adds = [i for i, statement in enumerate(sql) if statement.startswith(f"ALTER TABLE {table} ADD")]
        drops = [i for i, statement in enumerate(sql) if statement.startswith(f"ALTER TABLE {table} DROP")]
        assert max(adds) < min(drops)
