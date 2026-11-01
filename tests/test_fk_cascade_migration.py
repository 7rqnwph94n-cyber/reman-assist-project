"""Migration regressions using guarded SQLite DDL and offline PostgreSQL SQL.

These tests do not claim live PostgreSQL execution. The dedicated CI gate still
applies the complete migration chain against its disposable PostgreSQL service.
"""

from contextlib import contextmanager
from datetime import datetime
import io
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask
from flask_migrate import upgrade
import pytest
import sqlalchemy as sa

from app import create_app
from config import TestingConfig
from models import db
from scripts.migration_check import migration_script
from tests.db_safety import allow_database, assert_engine_database, forget_database


CASCADE_REVISION = "7b8c9d0e1f2a"
REPAIR_REVISION = "d2e3f4a5b6c7"
MIGRATIONS = str(Path(__file__).resolve().parents[1] / "migrations")

# Independent policy contract for all 24 FK changes, including the absent table.
# (source table, source column, referenced table, expected delete action)
EXPECTED_FKS = [
    ("survey_items", "job_id", "jobs", "CASCADE"),
    ("part_requirements", "job_id", "jobs", "CASCADE"),
    ("part_requirements", "survey_item_id", "survey_items", "SET NULL"),
    ("attachments", "job_id", "jobs", "CASCADE"),
    ("template_items", "template_id", "templates", "CASCADE"),
    ("template_groups", "template_id", "templates", "CASCADE"),
    ("template_item_groups", "template_item_id", "template_items", "CASCADE"),
    ("template_item_groups", "template_group_id", "template_groups", "CASCADE"),
    ("store_items", "template_item_id", "template_items", "CASCADE"),
    ("pick_lists", "job_id", "jobs", "CASCADE"),
    ("pick_list_items", "pick_list_id", "pick_lists", "CASCADE"),
    ("audit_logs", "job_id", "jobs", "CASCADE"),
    ("job_report_revisions", "job_id", "jobs", "CASCADE"),
    ("job_logs", "job_id", "jobs", "CASCADE"),
    ("pre_survey_results", "job_id", "jobs", "CASCADE"),
    ("epicor_settings", "template_id", "templates", "SET NULL"),
    ("job_costing_uploads", "job_id", "jobs", "CASCADE"),
    ("costing_template_profiles", "engine_template_id", "templates", "SET NULL"),
    ("costing_template_lines", "costing_template_profile_id", "costing_template_profiles", "CASCADE"),
    ("costing_sheets", "job_id", "jobs", "CASCADE"),
    ("costing_sheets", "job_costing_upload_id", "job_costing_uploads", "SET NULL"),
    ("costing_sheets", "costing_template_profile_id", "costing_template_profiles", "SET NULL"),
    ("costing_lines", "costing_sheet_id", "costing_sheets", "CASCADE"),
    ("costing_lines", "part_requirement_id", "part_requirements", "SET NULL"),
]


@pytest.fixture
def migration_app(tmp_path):
    database = allow_database(tmp_path / "migration.db", tmp_path)
    uri = f"sqlite:///{database}"
    app = create_app(TestingConfig, app_instance=Flask("app"), config_overrides={
        "SQLALCHEMY_DATABASE_URI": uri, "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "LOG_FILE": None, "REDIS_URL": "", "ENABLE_QUICKBOOKS": False,
    })
    try:
        with app.app_context():
            assert_engine_database(db.engine, uri)
            with db.engine.connect() as connection:
                assert sa.inspect(connection).get_table_names() == []
            yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        forget_database(database)


def run_repair(connection):
    module = migration_script().get_revision(REPAIR_REVISION).module
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


@pytest.fixture
def prefix_schema(migration_app):
    upgrade(directory=MIGRATIONS, revision="6a7b8c9d0e1f")
    return migration_app


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_all_fk_operations_match_the_actual_predecessor_schema(prefix_schema, monkeypatch, present, direction):
    with db.engine.begin() as connection:
        inspector = sa.inspect(connection)
        # Reproduce the fresh-chain omission without manufacturing model tables.
        assert not inspector.has_table("job_report_revisions")
        if present:
            run_repair(connection)
            inspector = sa.inspect(connection)
        emitted = io.StringIO()
        offline = Operations(MigrationContext.configure(dialect_name="postgresql", opts={
            "as_sql": True, "output_buffer": emitted,
        }))
        changes, dropped = [], []

        class Batch:
            def __init__(self, table, delegate):
                self.table, self.delegate = table, delegate

            def drop_constraint(self, name, **kwargs):
                existing = inspector.get_foreign_keys(self.table)
                names = {fk["name"] or f"{self.table}_{'_'.join(fk['constrained_columns'])}_fkey"
                         for fk in existing}
                assert name in names, (self.table, name, names)
                dropped.append((self.table, name))
                self.delegate.drop_constraint(name, **kwargs)

            def create_foreign_key(self, name, target, columns, target_columns, **kwargs):
                assert inspector.has_table(target)
                assert set(columns) <= {column["name"] for column in inspector.get_columns(self.table)}
                assert target_columns == ["id"]
                assert set(target_columns) <= {column["name"] for column in inspector.get_columns(target)}
                changes.append((self.table, columns[0], target, kwargs["ondelete"]))
                self.delegate.create_foreign_key(name, target, columns, target_columns, **kwargs)

        class TracingOperations:
            def get_bind(self):
                return offline.get_bind()

            @contextmanager
            def batch_alter_table(self, table, **kwargs):
                assert inspector.has_table(table), f"FK operation on absent table: {table}"
                with offline.batch_alter_table(table, **kwargs) as batch:
                    yield Batch(table, batch)

        module = migration_script().get_revision(CASCADE_REVISION).module
        monkeypatch.setattr(module, "op", TracingOperations())
        monkeypatch.setattr(module, "sa", SimpleNamespace(inspect=lambda bind: inspector))
        getattr(module, direction)()
        expected = [(source, column, target, action if direction == "upgrade" else None)
                    for source, column, target, action in EXPECTED_FKS
                    if present or source != "job_report_revisions"]
        assert sorted(changes, key=repr) == sorted(expected, key=repr)
        assert len(dropped) == len(expected) == (24 if present else 23)
        assert ("costing_sheets", "fk_costing_sheets_job_costing_upload") in dropped
        assert emitted.getvalue().count("DROP CONSTRAINT") == len(expected)
        assert emitted.getvalue().count("ADD CONSTRAINT") == len(expected)


@pytest.mark.parametrize("name", ["fk_costing_sheets_job_costing_upload", "costing_sheets_job_costing_upload_id_fkey"])
def test_costing_upload_fk_supports_alembic_and_legacy_names(monkeypatch, name):
    module = migration_script().get_revision(CASCADE_REVISION).module
    fk = {"name": name, "constrained_columns": ["job_costing_upload_id"],
          "referred_table": "job_costing_uploads", "referred_columns": ["id"]}
    monkeypatch.setattr(module, "sa", SimpleNamespace(inspect=lambda bind: SimpleNamespace(
        get_foreign_keys=lambda table: [fk])))
    assert module._costing_upload_fk_name(None) == name


@pytest.mark.parametrize("names", [[], [None], ["first", "second"]])
def test_costing_upload_fk_does_not_silently_skip_missing_or_ambiguous_constraints(monkeypatch, names):
    module = migration_script().get_revision(CASCADE_REVISION).module
    fks = [{"name": name, "constrained_columns": ["job_costing_upload_id"],
            "referred_table": "job_costing_uploads", "referred_columns": ["id"]} for name in names]
    monkeypatch.setattr(module, "sa", SimpleNamespace(inspect=lambda bind: SimpleNamespace(
        get_foreign_keys=lambda table: fks)))
    with pytest.raises(RuntimeError, match="exactly one named"):
        module._costing_upload_fk_name(None)


def test_forward_repair_creates_the_full_table_with_real_cascade_behavior(migration_app):
    with db.engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(sa.text("CREATE TABLE jobs (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        run_repair(connection)
        inspector = sa.inspect(connection)
        assert {column["name"] for column in inspector.get_columns("job_report_revisions")} == {
            "id", "job_id", "revision", "reason", "user_id", "created_at",
        }
        assert {index["name"] for index in inspector.get_indexes("job_report_revisions")} == {
            "ix_job_report_revisions_job_id", "ix_job_report_revisions_created_at",
        }
        foreign_keys = inspector.get_foreign_keys("job_report_revisions")
        assert {(fk["constrained_columns"][0], fk["referred_table"]) for fk in foreign_keys} == {
            ("job_id", "jobs"), ("user_id", "users"),
        }
        job_fk = next(fk for fk in foreign_keys if fk["constrained_columns"] == ["job_id"])
        assert job_fk["options"]["ondelete"] == "CASCADE"
        connection.execute(sa.text("INSERT INTO jobs (id) VALUES (1)"))
        connection.execute(sa.text("INSERT INTO users (id) VALUES (2)"))
        table = sa.Table("job_report_revisions", sa.MetaData(), autoload_with=connection)
        connection.execute(table.insert().values(job_id=1, revision=3, reason="retained", user_id=2,
                                                 created_at=datetime(2026, 1, 1)))
        assert connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 1
        connection.execute(sa.text("DELETE FROM jobs WHERE id=1"))
        assert connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 0


def test_existing_audit_rows_and_schema_survive_repair_and_refused_downgrade(migration_app):
    with db.engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE jobs (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO jobs (id) VALUES (1)"))
        run_repair(connection)
        table = sa.Table("job_report_revisions", sa.MetaData(), autoload_with=connection)
        connection.execute(table.insert().values(id=17, job_id=1, revision=4, reason="existing audit",
                                                 user_id=None, created_at=datetime(2026, 1, 1)))
        before = connection.execute(sa.select(table)).all()
        schema_query = sa.text("SELECT type, name, sql FROM sqlite_master WHERE tbl_name='job_report_revisions' ORDER BY type, name")
        schema_before = connection.execute(schema_query).all()
        run_repair(connection)
        assert connection.execute(sa.select(table)).all() == before
        assert connection.execute(schema_query).all() == schema_before
        module = migration_script().get_revision(REPAIR_REVISION).module
        with pytest.raises(RuntimeError, match="risk existing report revision audit data"):
            module.downgrade()
        assert connection.execute(sa.select(table)).all() == before


def test_incomplete_existing_table_fails_without_dropping_data(migration_app):
    with db.engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE job_report_revisions (id INTEGER PRIMARY KEY, reason TEXT)"))
        connection.execute(sa.text("INSERT INTO job_report_revisions VALUES (1, 'existing')"))
        with pytest.raises(RuntimeError, match="incomplete"):
            run_repair(connection)
        assert connection.execute(sa.text("SELECT reason FROM job_report_revisions")).scalar_one() == "existing"


def test_fresh_full_sqlite_migration_chain_includes_report_revisions(migration_app):
    upgrade(directory=MIGRATIONS, revision="head")
    script = migration_script()
    head = script.get_current_head()
    assert REPAIR_REVISION in {revision.revision for revision in script.walk_revisions(base="base", head=head)}
    with db.engine.connect() as connection:
        assert sa.inspect(connection).has_table("job_report_revisions")
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == head
