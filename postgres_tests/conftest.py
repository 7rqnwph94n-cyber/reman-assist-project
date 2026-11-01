"""Explicit opt-in suite using only a database verified by ci_postgres.py."""

import os
import pytest

from scripts.ci_postgres import read_receipt, schema_fingerprint, verify_receipt_server
from scripts.migration_check import check_database, migration_script
from tests.postgres_support import (
    activate_postgres_guards, assert_postgres_engine, configure_postgres_app,
    postgres_connection_checks, target_from_environment,
)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("REMAN_RUN_POSTGRES_TESTS") != "1":
        raise pytest.UsageError("postgres_tests requires explicit REMAN_RUN_POSTGRES_TESTS=1; no SQLite fallback")


@pytest.fixture(scope="session")
def postgres_app(tmp_path_factory):
    target = target_from_environment()
    receipt = read_receipt(os.environ.get("REMAN_PG_TEST_RECEIPT", ""), target)
    activate_postgres_guards(target)
    app = configure_postgres_app(target, tmp_path_factory.mktemp("postgres-app"))
    from models import db

    try:
        with app.app_context():
            assert_postgres_engine(db.engine, target)
            script = migration_script()
            if receipt["revision"] != script.get_current_head():
                raise RuntimeError("Migration receipt is not at the repository head")
            check_database(db.engine, script)
            with db.engine.connect() as connection:
                verify_receipt_server(connection, target, receipt)
                if schema_fingerprint(connection, db.metadata) != receipt["schema"]:
                    raise RuntimeError("PostgreSQL schema changed since migration verification")
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


@pytest.fixture
def client(postgres_app):
    return postgres_app.test_client()


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(
        f"PostgreSQL guards: {len(postgres_connection_checks)} exact-target connection checks."
    )
