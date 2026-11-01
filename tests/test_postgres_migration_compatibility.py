"""Socket-free migration checks; these do not replace the live PostgreSQL gate."""

import ast
import io
from pathlib import Path
import re
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask_migrate import upgrade
import pytest
import sqlalchemy as sa

from models import db
from scripts.migration_check import migration_script
from tests.test_fk_cascade_migration import migration_app  # Shared guarded empty-schema fixture.


ALIGNMENT_REVISION = "e3f4a5b6c7d8"
REVISIONS = list(migration_script().walk_revisions())
MIGRATIONS = str(Path(__file__).resolve().parents[1] / "migrations")
# These three revisions explicitly select PostgreSQL true/false versus SQLite
# integer defaults. Their PostgreSQL branches are also executed offline below.
DIALECT_DEFAULTS = {
    "af25d3f4c9ab": {"default_expr"},
    "cc_epicor_settings": {"is_active_default"},
    "bb8c9d0e1f2a": {"is_active_default", "auto_create_default"},
}


def boolean_default_errors(source, revision):
    errors = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "Column":
            continue
        column_type = node.args[1] if len(node.args) > 1 else None
        if isinstance(column_type, ast.Call):
            column_type = column_type.func
        if not isinstance(column_type, ast.Attribute) or column_type.attr != "Boolean":
            continue
        default = next((kw.value for kw in node.keywords if kw.arg == "server_default"), None)
        if default is None:
            continue
        if isinstance(default, ast.Name) and default.id in DIALECT_DEFAULTS.get(revision, set()):
            continue
        portable = (
            isinstance(default, ast.Call) and isinstance(default.func, ast.Attribute)
            and (default.func.attr in {"true", "false"} or (
                default.func.attr == "text" and len(default.args) == 1
                and isinstance(default.args[0], ast.Constant)
                and str(default.args[0].value).strip().lower() in {"true", "false"}
            ))
        )
        if not portable:
            errors.append(f"line {node.lineno}: Boolean server default must be typed true/false or explicitly audited")
    return errors


@pytest.mark.parametrize("revision", REVISIONS, ids=lambda revision: revision.revision)
def test_every_migration_uses_portable_boolean_defaults(revision):
    # Scan upgrade AND downgrade, including currently unexecuted branches.
    assert not boolean_default_errors(Path(revision.path).read_text(), revision.revision)


@pytest.mark.parametrize("expression", ["sa.text('0')", "sa.text('1')", "'0'", "1", "unreviewed_variable"])
def test_boolean_audit_rejects_numeric_and_unaudited_defaults(expression):
    source = f"sa.Column('flag', sa.Boolean(), server_default={expression})"
    assert boolean_default_errors(source, "new_revision")
    assert not boolean_default_errors(source.replace("sa.Boolean()", "sa.Integer()"), "new_revision")


@pytest.mark.parametrize("revision, expected", [
    ("462e693b8825", {"torque_confirmed"}),
    ("6f2c1a0b9d7e", {"requires_torque", "requires_build_measure", "requires_photo"}),
    ("ca2e176c395f", {"is_resolved"}),
    ("af25d3f4c9ab", {"force_password_reset"}),
    ("cc_epicor_settings", {"is_active"}),
    ("bb8c9d0e1f2a", {"is_active", "auto_create_customers"}),
])
def test_actual_postgres_upgrade_sql_uses_boolean_literals(monkeypatch, revision, expected):
    module = migration_script().get_revision(revision).module
    output = io.StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "output_buffer": output,
    }))
    inspector = SimpleNamespace(get_table_names=lambda: [], get_columns=lambda table: [],
                                get_indexes=lambda table: [])
    columns = []

    def column(*args, **kwargs):
        result = sa.Column(*args, **kwargs)
        if isinstance(result.type, sa.Boolean):
            columns.append(result)
        return result

    monkeypatch.setattr(module, "op", operations)
    monkeypatch.setattr(module, "sa", SimpleNamespace(**{
        **vars(sa), "Column": column, "inspect": lambda bind: inspector,
    }))
    module.upgrade()
    assert {column.name for column in columns} == expected
    for column in columns:
        assert str(column.server_default.arg.compile(dialect=operations.get_bind().dialect)).lower() in {"false", "true"}
    sql = output.getvalue()
    assert len(re.findall(r"BOOLEAN DEFAULT (?:false|true)\b", sql)) == len(expected)
    assert not re.search(r"BOOLEAN DEFAULT ['\"]?[01]\b", sql)
    if revision in {"ca2e176c395f", "af25d3f4c9ab"}:
        assert "DROP DEFAULT" in sql  # Preserve the original temporary backfill default.


def run_revision(connection, revision, direction="upgrade"):
    module = migration_script().get_revision(revision).module
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.mark.parametrize("revision, table, columns, retained", [
    ("462e693b8825", "survey_items", ["torque_confirmed"], True),
    ("6f2c1a0b9d7e", "template_items", ["requires_torque", "requires_build_measure", "requires_photo"], True),
    ("ca2e176c395f", "survey_items", ["is_resolved"], False),
])
def test_boolean_backfill_and_targeted_downgrade_preserve_existing_rows(migration_app, revision, table, columns, retained):
    with db.engine.begin() as connection:
        connection.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"))
        connection.execute(sa.text(f"INSERT INTO {table} VALUES (1, 'keep this row')"))
        run_revision(connection, revision)
        fields = ", ".join(columns)
        assert connection.execute(sa.text(f"SELECT {fields} FROM {table} WHERE id=1")).one() == tuple(0 for _ in columns)
        actual = {column["name"]: column for column in sa.inspect(connection).get_columns(table)}
        for column in columns:
            assert (actual[column]["default"] is not None) == retained
            assert actual[column]["nullable"] == (revision != "ca2e176c395f")
            # Defaults backfill old rows; explicit true values remain writable.
            connection.execute(sa.text(f"UPDATE {table} SET {column}=1 WHERE id=1"))
        if revision == "462e693b8825":
            run_revision(connection, revision)  # Its existing-column path must retain true values.
        assert connection.execute(sa.text(f"SELECT {fields} FROM {table} WHERE id=1")).one() == tuple(1 for _ in columns)
        run_revision(connection, revision, "downgrade")
        assert connection.execute(sa.text(f"SELECT id, marker FROM {table}")).all() == [(1, "keep this row")]
        assert set(columns).isdisjoint({column["name"] for column in sa.inspect(connection).get_columns(table)})


@pytest.fixture
def legacy_schema(migration_app):
    upgrade(directory=MIGRATIONS, revision="d2e3f4a5b6c7")
    with db.engine.connect() as connection:
        org_id = connection.execute(sa.text("SELECT id FROM organizations WHERE slug='global-reman'")).scalar_one()
        connection.execute(sa.text(
            "INSERT INTO jobs (id, job_number, job_pack_id, status, survey_layout, organization_id, survey_version, parts_version) "
            "VALUES (123, 'compat-123', 'compat-123', 'PRE_SURVEY', 'table', :org, 0, 0)"
        ), {"org": org_id})
        connection.execute(sa.text(
            "INSERT INTO job_costing_uploads (id, job_id, version, file_path, uploaded_at) "
            "VALUES (456, 123, 1, 'test-owned-placeholder.xlsx', '2026-01-01 12:00:00')"
        ))
        connection.commit()
        yield connection


def rows(connection):
    return {table: connection.execute(sa.text(f"SELECT * FROM {table} ORDER BY id")).all()
            for table in ("organizations", "jobs", "job_costing_uploads")}


def test_forward_alignment_preserves_records_and_repeated_upgrade(legacy_schema):
    connection = legacy_schema
    before = rows(connection)
    for table, column in (("organizations", "slug"), ("job_costing_uploads", "uploaded_at")):
        assert next(item for item in sa.inspect(connection).get_columns(table) if item["name"] == column)["nullable"]
    run_revision(connection, ALIGNMENT_REVISION)
    for table, column in (("organizations", "slug"), ("job_costing_uploads", "uploaded_at")):
        assert not next(item for item in sa.inspect(connection).get_columns(table) if item["name"] == column)["nullable"]
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text(f"UPDATE {table} SET {column}=NULL"))
    assert rows(connection) == before
    schema = connection.execute(sa.text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()
    run_revision(connection, ALIGNMENT_REVISION)
    assert rows(connection) == before
    assert connection.execute(sa.text("SELECT name, sql FROM sqlite_master ORDER BY name")).all() == schema
    with pytest.raises(RuntimeError, match="cannot safely remove HOLD"):
        run_revision(connection, ALIGNMENT_REVISION, "downgrade")
    assert rows(connection) == before


@pytest.mark.parametrize("table, column", [("organizations", "slug"), ("job_costing_uploads", "uploaded_at")])
def test_forward_alignment_refuses_nulls_before_any_schema_changes(legacy_schema, table, column):
    connection = legacy_schema
    connection.execute(sa.text(f"UPDATE {table} SET {column}=NULL"))
    before = rows(connection)
    schema = connection.execute(sa.text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()
    with pytest.raises(RuntimeError, match=rf"{table}\.{column}.*manual data review"):
        run_revision(connection, ALIGNMENT_REVISION)
    assert rows(connection) == before
    assert connection.execute(sa.text("SELECT name, sql FROM sqlite_master ORDER BY name")).all() == schema


def test_forward_alignment_refuses_sqlite_rebuild_with_foreign_keys_enabled(legacy_schema):
    connection = legacy_schema
    connection.execute(sa.text("PRAGMA foreign_keys=ON"))
    assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar_one() == 1
    before = rows(connection)
    schema = connection.execute(sa.text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()
    with pytest.raises(RuntimeError, match="parent-table rebuild.*unsafe"):
        run_revision(connection, ALIGNMENT_REVISION)
    assert rows(connection) == before
    assert connection.execute(sa.text("SELECT name, sql FROM sqlite_master ORDER BY name")).all() == schema


def test_forward_postgres_sql_adds_hold_and_only_expected_constraints(legacy_schema, monkeypatch):
    output = io.StringIO()
    operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "output_buffer": output,
    }))
    module = migration_script().get_revision(ALIGNMENT_REVISION).module
    bind = SimpleNamespace(dialect=operations.get_bind().dialect, execute=legacy_schema.execute)
    monkeypatch.setattr(module, "op", SimpleNamespace(
        get_bind=lambda: bind, execute=operations.execute, batch_alter_table=operations.batch_alter_table,
    ))
    monkeypatch.setattr(module, "sa", SimpleNamespace(**{
        **vars(sa), "inspect": lambda bind: sa.inspect(legacy_schema),
    }))
    module.upgrade()
    assert [sql.strip() for sql in output.getvalue().split(";") if sql.strip()] == [
        "ALTER TYPE jobstatusenum ADD VALUE IF NOT EXISTS 'HOLD'",
        "ALTER TABLE organizations ALTER COLUMN slug SET NOT NULL",
        "ALTER TABLE job_costing_uploads ALTER COLUMN uploaded_at SET NOT NULL",
    ]


def test_migration_enum_label_inventory_covers_every_current_model_enum():
    # Source inventory, not a PostgreSQL catalog query. The live gate still
    # verifies the actual labels after transactional migration execution.
    labels = {}
    for revision in REVISIONS:
        for node in ast.walk(ast.parse(Path(revision.path).read_text())):
            if isinstance(node, ast.Call):
                kind = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if kind in {"Enum", "ENUM", "EnumType"}:
                    name = next((kw.value.value for kw in node.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)), None)
                    if name:
                        labels.setdefault(name, set()).update(arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                match = re.fullmatch(r"ALTER TYPE (\w+) ADD VALUE IF NOT EXISTS '([^']+)'", node.value)
                if match:
                    labels.setdefault(match[1], set()).add(match[2])
    for table in db.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, sa.Enum):
                assert set(column.type.enums) == labels[column.type.name], (table.name, column.name)
