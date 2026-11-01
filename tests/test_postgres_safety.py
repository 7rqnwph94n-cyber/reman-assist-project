"""Socket-free unit tests; these are not PostgreSQL integration results."""

import json

import pytest
from sqlalchemy import create_engine

from scripts.ci_postgres import read_receipt
from tests import postgres_support as support


@pytest.fixture
def environment():
    return {
        "REMAN_RUN_POSTGRES_TESTS": "1", "REMAN_PG_TEST_ID": "12345_1",
        "REMAN_PG_TEST_HOST": support.TEST_HOST, "REMAN_PG_TEST_PORT": "15432",
        "REMAN_PG_TEST_DATABASE": "reman_pg_test_12345_1",
        "REMAN_PG_TEST_USER": support.TEST_USER, "REMAN_PG_TEST_PASSWORD": support.TEST_PASSWORD,
    }


@pytest.fixture
def target(environment, monkeypatch):
    for key in list(support.os.environ):
        if key.startswith("PG"):
            monkeypatch.delenv(key)
    target = support.target_from_environment(environment)
    monkeypatch.setattr(support, "_active_target", target)
    monkeypatch.setattr(support, "postgres_connection_checks", [])
    return target


@pytest.fixture
def receipt(target):
    return {
        "format": 1, "target": target.identity,
        "server": {"cluster_id": "123456789", "database_oid": "16384", "server_version_num": 160011},
        "revision": "c1d2e3f4a5b6", "schema": "a" * 64,
    }


def test_only_dedicated_configuration_is_used(environment):
    environment["DATABASE_URL"] = "postgresql://unapproved.invalid/application"
    target = support.target_from_environment(environment)
    assert target.url.host == "127.0.0.1"
    assert target.url.port == 15432
    assert target.url.database == "reman_pg_test_12345_1"
    assert target.url.username == support.TEST_USER
    assert target.url.password == support.TEST_PASSWORD
    assert target.url.drivername == "postgresql+psycopg2"


@pytest.mark.parametrize("key,value", [
    ("REMAN_RUN_POSTGRES_TESTS", "0"), ("REMAN_RUN_POSTGRES_TESTS", ""),
    ("REMAN_PG_TEST_HOST", "production.invalid"), ("REMAN_PG_TEST_HOST", "localhost"),
    ("REMAN_PG_TEST_HOST", "/tmp/socket"), ("REMAN_PG_TEST_USER", "postgres"),
    ("REMAN_PG_TEST_PASSWORD", "different"), ("REMAN_PG_TEST_DATABASE", "application"),
    ("REMAN_PG_TEST_DATABASE", "reman_pg_test_other"), ("REMAN_PG_TEST_PORT", "0"),
    ("REMAN_PG_TEST_PORT", "65536"), ("REMAN_PG_TEST_PORT", "5432,5433"),
    ("REMAN_PG_TEST_PORT", " 5432"), ("REMAN_PG_TEST_ID", ""),
    ("REMAN_PG_TEST_ID", "x'; DROP DATABASE x;--"), ("REMAN_PG_TEST_ID", "A" * 40),
    ("PGHOSTADDR", "192.0.2.1"), ("PGSERVICE", "production"), ("PGOPTIONS", "-c role=postgres"),
])
def test_unsafe_or_incomplete_configuration_is_refused(environment, key, value):
    environment[key] = value
    with pytest.raises(RuntimeError):
        support.target_from_environment(environment)


@pytest.mark.parametrize("key,value", [
    ("host", "192.0.2.1"), ("hostaddr", "192.0.2.1"), ("port", "5432"),
    ("dbname", "application"), ("user", "postgres"), ("password", "different"),
    ("service", "other"), ("options", "-c search_path=other"),
    ("sslmode", "disable"), ("connect_timeout", "60"), ("application_name", "other"),
])
def test_connection_target_and_options_cannot_be_overridden(target, key, value):
    parameters = {**target.connection_parameters, key: value}
    with pytest.raises(RuntimeError, match="non-designated"):
        support.require_postgres_connection((), parameters)
    assert support.postgres_connection_checks == []


@pytest.mark.parametrize("use_dsn", [False, True])
def test_exact_designated_parameters_are_accepted_without_connecting(target, use_dsn):
    from psycopg2.extensions import make_dsn

    parameters = target.connection_parameters
    if use_dsn:
        support.require_postgres_connection((make_dsn(**parameters),), {})
    else:
        engine = create_engine(target.url)
        try:
            cargs, cparams = engine.dialect.create_connect_args(engine.url)
            support.require_postgres_connection(cargs, {**cparams, **target.connect_args})
        finally:
            engine.dispose()
    assert support.postgres_connection_checks == [target.identity]


def test_conflicting_dsn_and_inherited_options_are_refused(target, monkeypatch):
    from psycopg2.extensions import make_dsn

    with pytest.raises(RuntimeError, match="Conflicting"):
        support.require_postgres_connection((make_dsn(**target.connection_parameters),), {"host": "elsewhere"})
    monkeypatch.setenv("PGSERVICE", "unapproved")
    with pytest.raises(RuntimeError, match=r"PG\*"):
        support.require_postgres_connection((), target.connection_parameters)


def test_sqlalchemy_refuses_postgres_before_any_driver_call(environment, monkeypatch):
    import psycopg2

    def forbidden_driver(*args, **kwargs):
        pytest.fail("A PostgreSQL driver connection was attempted by a socket-free unit test")

    monkeypatch.setattr(psycopg2, "connect", forbidden_driver)
    monkeypatch.setattr(support, "_active_target", None)
    target = support.target_from_environment(environment)
    engine = create_engine(target.url, connect_args=target.connect_args)
    try:
        with pytest.raises(RuntimeError, match="not been explicitly designated"):
            engine.connect()
    finally:
        engine.dispose()


def test_raw_driver_guard_rejects_before_calling_fake_driver(target, monkeypatch):
    import psycopg2

    calls = []
    sentinel = object()

    def fake_driver(*args, **kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(psycopg2, "connect", fake_driver)
    monkeypatch.setattr(support, "_driver_guard_installed", False)
    support.activate_postgres_guards(target)
    assert psycopg2.connect(**target.connection_parameters) is sentinel
    with pytest.raises(RuntimeError, match="non-designated"):
        psycopg2.connect(**{**target.connection_parameters, "dbname": "existing_application"})
    assert len(calls) == 1


def test_effective_engine_cannot_substitute_sqlite(target):
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(RuntimeError, match="Effective engine"):
            support.assert_postgres_engine(engine, target)
    finally:
        engine.dispose()


def test_migration_command_refuses_opt_out_before_engine_creation(monkeypatch, tmp_path):
    from scripts import ci_postgres

    monkeypatch.delenv("REMAN_RUN_POSTGRES_TESTS", raising=False)

    def forbidden_engine(*args, **kwargs):
        pytest.fail("An engine was created without explicit PostgreSQL opt-in")

    monkeypatch.setattr(ci_postgres, "create_engine", forbidden_engine)
    with pytest.raises(RuntimeError, match="explicit"):
        ci_postgres.main(["--receipt", str(tmp_path / "new-receipt.json")])


def test_receipt_must_match_target_and_be_regular_file(target, receipt, tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps({"target": {**target.identity, "database": "different"}}))
    with pytest.raises(RuntimeError, match="different PostgreSQL"):
        read_receipt(path, target)
    path.write_text(json.dumps(receipt))
    assert read_receipt(path, target)["target"] == target.identity
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(RuntimeError, match="receipt file"):
        read_receipt(alias, target)


@pytest.mark.parametrize("field,value", [
    ("run_id", "other"), ("host", "192.0.2.1"), ("port", 15433),
    ("database", "reman_pg_test_other"), ("user", "other"),
])
def test_receipt_cannot_be_reused_for_another_target(target, receipt, tmp_path, field, value):
    receipt["target"][field] = value
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(RuntimeError, match="different PostgreSQL test target"):
        read_receipt(path, target)


@pytest.mark.parametrize("mutation", ["legacy", "oid", "version", "schema", "revision"])
def test_incomplete_or_obsolete_receipt_is_rejected(target, receipt, tmp_path, mutation):
    if mutation == "legacy":
        receipt["server"].pop("database_oid")
    elif mutation == "oid":
        receipt["server"]["database_oid"] = "not-an-oid"
    elif mutation == "version":
        receipt["server"]["server_version_num"] = 170000
    elif mutation == "schema":
        receipt["schema"] = "missing"
    else:
        receipt["revision"] = ""
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(RuntimeError, match="obsolete"):
        read_receipt(path, target)


@pytest.mark.parametrize("change", [None, "database_oid", "cluster_id"])
def test_receipt_is_bound_to_database_instance(target, receipt, change):
    from scripts.ci_postgres import verify_receipt_server

    row = {
        "database": target.database, "username": support.TEST_USER,
        "session_user": support.TEST_USER, "owner": support.TEST_USER,
        "application": support.APPLICATION_NAME, "server_port": 5432,
        "version": 160011, "cluster_id": receipt["server"]["cluster_id"],
        "database_oid": receipt["server"]["database_oid"],
    }
    if change:
        row[change] = "987654321"

    class IdentityConnection:
        def execute(self, statement):
            assert "oid::text" in str(statement)
            return self

        def mappings(self):
            return self

        def one(self):
            return row

    if change:
        # The name/host/port stay identical, but this is a different instance.
        with pytest.raises(RuntimeError, match="database instance"):
            verify_receipt_server(IdentityConnection(), target, receipt)
    else:
        verify_receipt_server(IdentityConnection(), target, receipt)


@pytest.mark.parametrize("schema", ["pgx_data", "pgadata", "application"])
def test_existing_user_schemas_are_never_treated_as_system_schemas(schema):
    class CatalogConnection:
        def execute(self, statement):
            return self

        def scalars(self):
            return self

        def all(self):
            return ["public", "information_schema", "pg_catalog", "pg_toast", schema]

    with pytest.raises(RuntimeError, match="contains a user schema"):
        support.require_empty_postgres(CatalogConnection())


@pytest.mark.parametrize("public_objects", [0, 1])
def test_empty_check_requires_no_public_objects(public_objects):
    class CatalogConnection:
        def execute(self, statement):
            return self

        def scalars(self):
            return self

        def all(self):
            return ["public", "information_schema", "pg_catalog", "pg_toast", "pg_temp_3"]

        def scalar_one(self):
            return public_objects

    if public_objects:
        with pytest.raises(RuntimeError, match="not empty"):
            support.require_empty_postgres(CatalogConnection())
    else:
        support.require_empty_postgres(CatalogConnection())


@pytest.mark.parametrize("override", ["host", "database", "password", "query", "connect_args"])
def test_sqlalchemy_overrides_are_rejected_before_driver_call(target, monkeypatch, override):
    import psycopg2

    def forbidden_driver(*args, **kwargs):
        pytest.fail("SQLAlchemy redirected a connection past the test guard")

    monkeypatch.setattr(psycopg2, "connect", forbidden_driver)
    url, arguments = target.url, target.connect_args
    if override == "host":
        url = url.set(host="192.0.2.1")
    elif override == "database":
        url = url.set(database="existing_application")
    elif override == "password":
        url = url.set(password="different")
    elif override == "query":
        url = url.set(query={"hostaddr": "192.0.2.1"})
    else:
        arguments = {**arguments, "port": 15433}
    engine = create_engine(url, connect_args=arguments)
    try:
        with pytest.raises(RuntimeError, match="non-designated"):
            engine.connect()
    finally:
        engine.dispose()


@pytest.mark.parametrize("mutation", ["table", "index", "default", "check", "sequence", "view", "enum"])
def test_repeatability_fingerprint_detects_non_model_schema_drift(monkeypatch, mutation):
    from sqlalchemy import Column, Integer, MetaData, Table
    from scripts import ci_postgres

    metadata = MetaData()
    Table("model_table", metadata, Column("id", Integer, primary_key=True))

    class Inspector:
        changed = False

        def get_table_names(self, **kwargs):
            return ["model_table"] + (["non_model_table"] if self.changed and mutation == "table" else [])

        def get_columns(self, name, **kwargs):
            return [{"name": "id", "type": Integer(), "nullable": False,
                     "default": "2" if self.changed and mutation == "default" else "1"}]

        def get_pk_constraint(self, *args, **kwargs):
            return {"constrained_columns": ["id"], "name": "example_pkey"}

        def get_foreign_keys(self, *args, **kwargs):
            return []

        def get_unique_constraints(self, *args, **kwargs):
            return []

        def get_indexes(self, *args, **kwargs):
            return [{"name": "extra_index", "column_names": ["id"], "unique": False}] if self.changed and mutation == "index" else []

        def get_check_constraints(self, *args, **kwargs):
            return [{"name": "extra_check", "sqltext": "id > 0"}] if self.changed and mutation == "check" else []

        def get_sequence_names(self, **kwargs):
            return ["extra_sequence"] if self.changed and mutation == "sequence" else []

        def get_view_names(self, **kwargs):
            return ["extra_view"] if self.changed and mutation == "view" else []

        def get_view_definition(self, *args, **kwargs):
            return "SELECT id FROM model_table"

        def get_materialized_view_names(self, **kwargs):
            return []

        def get_enums(self, **kwargs):
            return [{"name": "extra_enum", "labels": ["a"]}] if self.changed and mutation == "enum" else []

    inspector = Inspector()
    monkeypatch.setattr(ci_postgres, "inspect", lambda connection: inspector)
    before = ci_postgres.schema_fingerprint(None, metadata)
    assert ci_postgres.schema_fingerprint(None, metadata) == before
    inspector.changed = True
    assert ci_postgres.schema_fingerprint(None, metadata) != before
