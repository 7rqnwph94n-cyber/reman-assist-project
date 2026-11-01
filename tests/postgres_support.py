"""Fail-closed PostgreSQL test configuration; no connection on import."""

from dataclasses import dataclass
import os
import re

from sqlalchemy import URL, text


TEST_HOST = "127.0.0.1"
TEST_USER = "reman_pg_test"
TEST_PASSWORD = "reman-postgres-ci-only"
APPLICATION_NAME = "reman-ci-postgres"
_active_target = None
_driver_guard_installed = False
postgres_connection_checks = []


@dataclass(frozen=True)
class PostgresTestTarget:
    run_id: str
    port: int

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,31}", self.run_id):
            raise RuntimeError("Invalid PostgreSQL test run ID")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise RuntimeError("Invalid PostgreSQL test port")

    @property
    def database(self):
        return f"reman_pg_test_{self.run_id}"

    @property
    def url(self):
        return URL.create(
            "postgresql+psycopg2", username=TEST_USER, password=TEST_PASSWORD,
            host=TEST_HOST, port=self.port, database=self.database,
        )

    @property
    def connect_args(self):
        return {"connect_timeout": 5, "application_name": APPLICATION_NAME}

    @property
    def identity(self):
        return {
            "run_id": self.run_id, "host": TEST_HOST, "port": self.port,
            "database": self.database, "user": TEST_USER,
        }

    @property
    def connection_parameters(self):
        return {
            "host": TEST_HOST, "port": str(self.port), "dbname": self.database,
            "user": TEST_USER, "password": TEST_PASSWORD,
            **{key: str(value) for key, value in self.connect_args.items()},
        }


def reject_libpq_environment(environment):
    # PGHOSTADDR/PGSERVICE/PGOPTIONS etc. could redirect an otherwise safe DSN.
    if any(key.startswith("PG") for key in environment):
        raise RuntimeError("Remove inherited libpq PG* environment settings for this test gate")


def target_from_environment(environment=None):
    env = os.environ if environment is None else environment
    if env.get("REMAN_RUN_POSTGRES_TESTS") != "1":
        raise RuntimeError("PostgreSQL requires explicit REMAN_RUN_POSTGRES_TESTS=1 opt-in")
    reject_libpq_environment(env)
    if env.get("REMAN_PG_TEST_HOST") != TEST_HOST:
        raise RuntimeError("Only the designated loopback PostgreSQL test host is allowed")
    if env.get("REMAN_PG_TEST_USER") != TEST_USER or env.get("REMAN_PG_TEST_PASSWORD") != TEST_PASSWORD:
        raise RuntimeError("Only the fixed test-only PostgreSQL credentials are allowed")
    port = env.get("REMAN_PG_TEST_PORT", "")
    if not re.fullmatch(r"[1-9][0-9]{0,4}", port):
        raise RuntimeError("Invalid PostgreSQL test port")
    target = PostgresTestTarget(env.get("REMAN_PG_TEST_ID", ""), int(port))
    if env.get("REMAN_PG_TEST_DATABASE") != target.database:
        raise RuntimeError("PostgreSQL database must exactly match the designated test run")
    return target


def require_postgres_connection(cargs, cparams):
    if _active_target is None:
        raise RuntimeError("PostgreSQL target has not been explicitly designated")
    reject_libpq_environment(os.environ)
    if len(cargs) > 1:
        raise RuntimeError("Unexpected PostgreSQL connection arguments")
    from psycopg2.extensions import parse_dsn

    parameters = parse_dsn(cargs[0]) if cargs and cargs[0] else {}
    for key, value in cparams.items():
        if key in parameters and parameters[key] != str(value):
            raise RuntimeError("Conflicting PostgreSQL connection arguments")
        parameters[key] = str(value)
    if parameters != _active_target.connection_parameters:
        raise RuntimeError("PostgreSQL guard refused a non-designated connection target or options")
    postgres_connection_checks.append(dict(_active_target.identity))


def activate_postgres_guards(target):
    global _active_target, _driver_guard_installed
    # Revalidate even a caller-supplied object; only the fixed URL is permitted.
    if type(target) is not PostgresTestTarget:
        raise RuntimeError("Expected a validated PostgreSQL test target")
    if _active_target is not None and _active_target != target:
        raise RuntimeError("Cannot replace an active PostgreSQL test target")
    reject_libpq_environment(os.environ)
    from tests.db_safety import install_connection_guards
    import psycopg2

    install_connection_guards()
    _active_target = target
    if not _driver_guard_installed:
        original_connect = psycopg2.connect

        def guarded_connect(*args, **kwargs):
            require_postgres_connection(args, kwargs)
            return original_connect(*args, **kwargs)

        psycopg2.connect = guarded_connect
        _driver_guard_installed = True


def assert_postgres_engine(engine, target):
    if engine.dialect.name != "postgresql" or engine.url != target.url:
        raise RuntimeError("Effective engine does not match the designated PostgreSQL test database")


def configure_postgres_app(target, temporary_root):
    """Prepare a fresh app without reading application .env files or credentials."""
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1", "FLASK_CONFIG": "testing",
        "FLASK_ENV": "development", "APP_ENV": "test",
        "DATABASE_URL": target.url.render_as_string(hide_password=False),
        "SECRET_KEY": "disposable-postgres-test-key-only",
        "UPLOAD_FOLDER": str(temporary_root / "uploads"),
        "LOG_FILE": str(temporary_root / "app.log"),
        "REDIS_URL": "", "ENABLE_QUICKBOOKS": "0", "ENABLE_DEV_TOOLS": "0",
    })
    from flask import Flask
    from app import create_app
    from config import TestingConfig

    return create_app(TestingConfig, app_instance=Flask("app"), config_overrides={
        "SQLALCHEMY_DATABASE_URI": target.url.render_as_string(hide_password=False),
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True, "connect_args": target.connect_args},
        "UPLOAD_FOLDER": str(temporary_root / "uploads"), "LOG_FILE": None,
        "REDIS_URL": "", "ENABLE_QUICKBOOKS": False, "ENABLE_DEV_TOOLS": False,
    })


def verify_postgres_identity(connection, target):
    row = connection.execute(text("""
        SELECT current_database() AS database, current_user AS username,
               session_user AS session_user,
               current_setting('server_version_num')::int AS version,
               current_setting('application_name') AS application,
               inet_server_port() AS server_port,
               (SELECT pg_get_userbyid(datdba) FROM pg_database
                WHERE datname = current_database()) AS owner,
               (SELECT oid::text FROM pg_database
                WHERE datname = current_database()) AS database_oid,
               (SELECT system_identifier::text FROM pg_control_system()) AS cluster_id
    """)).mappings().one()
    if (row["database"] != target.database or row["username"] != TEST_USER
            or row["session_user"] != TEST_USER or row["owner"] != TEST_USER
            or row["application"] != APPLICATION_NAME or row["server_port"] != 5432
            or not 160000 <= row["version"] < 170000):
        raise RuntimeError("PostgreSQL database/server/role identity does not match the test service")
    return {
        "cluster_id": row["cluster_id"], "database_oid": row["database_oid"],
        "server_version_num": row["version"],
    }


def require_empty_postgres(connection):
    schemas = connection.execute(text("SELECT nspname FROM pg_namespace")).scalars().all()
    if any(name not in {"public", "information_schema"} and not name.startswith("pg_") for name in schemas):
        raise RuntimeError("Refusing migrations: PostgreSQL test database contains a user schema")
    count = connection.execute(text("""
        SELECT
          (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
             WHERE n.nspname='public') +
          (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
             WHERE n.nspname='public') +
          (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
             WHERE n.nspname='public')
    """)).scalar_one()
    if count != 0:
        raise RuntimeError("Refusing migrations: PostgreSQL test database is not empty")
