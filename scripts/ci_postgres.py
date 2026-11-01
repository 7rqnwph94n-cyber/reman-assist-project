#!/usr/bin/env python3
"""Opt-in PostgreSQL 16 gate. Never creates, drops, resets or stamps a database."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import time

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from scripts.migration_check import check_database, check_graph, migration_script
from tests.postgres_support import (
    activate_postgres_guards, assert_postgres_engine, configure_postgres_app,
    require_empty_postgres, target_from_environment, verify_postgres_identity,
)


def schema_fingerprint(connection, metadata):
    """Check model tables, columns, enum labels, FKs and uniqueness after upgrade."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema="public"))
    for table in metadata.sorted_tables:
        if table.name not in tables:
            raise RuntimeError(f"Migrated schema is missing table {table.name}")
        columns = {column["name"]: column for column in inspector.get_columns(table.name, schema="public")}
        foreign_keys = inspector.get_foreign_keys(table.name, schema="public")
        primary_key = inspector.get_pk_constraint(table.name, schema="public")["constrained_columns"]
        if primary_key != [column.name for column in table.primary_key.columns]:
            raise RuntimeError(f"Primary key differs for {table.name}")
        for column in table.columns:
            if column.name not in columns:
                raise RuntimeError(f"Migrated schema is missing {table.name}.{column.name}")
            actual = columns[column.name]
            if not column.nullable and actual["nullable"]:
                raise RuntimeError(f"Missing NOT NULL constraint on {table.name}.{column.name}")
            expected_enum = getattr(column.type, "enums", None)
            if expected_enum is not None and set(getattr(actual["type"], "enums", ())) != set(expected_enum):
                raise RuntimeError(f"Enum labels differ for {table.name}.{column.name}")
            for foreign_key in column.foreign_keys:
                referenced = foreign_key.column
                if not any(
                    fk["constrained_columns"] == [column.name]
                    and fk["referred_table"] == referenced.table.name
                    and fk["referred_columns"] == [referenced.name]
                    for fk in foreign_keys
                ):
                    raise RuntimeError(f"Missing foreign key on {table.name}.{column.name}")
        unique_sets = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table.name, schema="public")
        }
        unique_sets.update(
            tuple(index["column_names"]) for index in inspector.get_indexes(table.name, schema="public")
            if index["unique"]
        )
        from sqlalchemy import UniqueConstraint
        expected_unique = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
        }
        expected_unique.update(
            tuple(column.name for column in index.columns) for index in table.indexes if index.unique
        )
        if not expected_unique <= unique_sets:
            raise RuntimeError(f"Missing unique constraints on {table.name}")
    # Include every public table, not only tables currently represented by models.
    # Defaults and non-unique indexes must also participate in repeatability checks.
    catalog = {}
    for name in sorted(tables):
        catalog[name] = {
            "columns": [{**column, "type": str(column["type"]),
                         "enum": getattr(column["type"], "enums", None)}
                        for column in inspector.get_columns(name, schema="public")],
            "primary_key": inspector.get_pk_constraint(name, schema="public"),
            "foreign_keys": inspector.get_foreign_keys(name, schema="public"),
            "indexes": inspector.get_indexes(name, schema="public"),
            "unique": inspector.get_unique_constraints(name, schema="public"),
            "checks": inspector.get_check_constraints(name, schema="public"),
        }
    actual_schema = {
        "tables": catalog,
        "sequences": sorted(inspector.get_sequence_names(schema="public")),
        "views": {name: inspector.get_view_definition(name, schema="public")
                  for name in sorted(inspector.get_view_names(schema="public"))},
        "materialized_views": {name: inspector.get_view_definition(name, schema="public")
                               for name in sorted(inspector.get_materialized_view_names(schema="public"))},
        "enums": sorted(inspector.get_enums(schema="public"), key=lambda item: item["name"]),
    }
    return hashlib.sha256(json.dumps(actual_schema, sort_keys=True, default=str).encode()).hexdigest()


def read_receipt(path, target):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("An explicit migration receipt file is required")
    receipt = json.loads(path.read_text())
    if not isinstance(receipt, dict):
        raise RuntimeError("Invalid PostgreSQL migration receipt")
    if receipt.get("target") != target.identity:
        raise RuntimeError("Migration receipt belongs to a different PostgreSQL test target")
    server = receipt.get("server")
    if (receipt.get("format") != 1 or not isinstance(server, dict)
            or set(server) != {"cluster_id", "database_oid", "server_version_num"}
            or not all(isinstance(server.get(key), str) and server[key].isascii()
                       and server[key].isdecimal() and int(server[key]) > 0
                       for key in ("cluster_id", "database_oid"))
            or type(server.get("server_version_num")) is not int
            or not 160000 <= server["server_version_num"] < 170000
            or not isinstance(receipt.get("revision"), str) or not receipt["revision"]
            or not isinstance(receipt.get("schema"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["schema"])):
        raise RuntimeError("Invalid or obsolete PostgreSQL migration receipt")
    return receipt


def verify_receipt_server(connection, target, receipt):
    if verify_postgres_identity(connection, target) != receipt["server"]:
        raise RuntimeError("Migration receipt belongs to a different PostgreSQL server or database instance")


def wait_for_service(engine):
    for attempt in range(20):
        try:
            with engine.connect():
                return
        except OperationalError:
            if attempt == 19:
                raise
            time.sleep(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.receipt.is_absolute() or args.receipt.exists() or args.receipt.is_symlink():
        raise RuntimeError("Receipt must be a new absolute file path; existing files are never replaced")
    target = target_from_environment()
    activate_postgres_guards(target)
    script = migration_script()
    check_graph(script)
    engine = create_engine(target.url, connect_args=target.connect_args)
    try:
        assert_postgres_engine(engine, target)
        wait_for_service(engine)
        with engine.connect() as connection:
            identity = verify_postgres_identity(connection, target)
            require_empty_postgres(connection)
        print(f"VERIFIED_EMPTY_POSTGRES_TARGET={json.dumps(target.identity, sort_keys=True)}")
    finally:
        engine.dispose()

    with TemporaryDirectory(prefix="reman-pg-gate-") as directory:
        app = configure_postgres_app(target, Path(directory))
        from flask_migrate import upgrade
        from models import db

        with app.app_context():
            try:
                assert_postgres_engine(db.engine, target)
                with db.engine.connect() as connection:
                    if verify_postgres_identity(connection, target) != identity:
                        raise RuntimeError("PostgreSQL server identity changed during setup")
                    require_empty_postgres(connection)
                upgrade(directory=str(ROOT_DIR / "migrations"), revision="head")
                check_database(db.engine, script)
                with db.engine.connect() as connection:
                    fingerprint = schema_fingerprint(connection, db.metadata)
                # Upgrading the same freshly migrated test DB again must be a no-op.
                upgrade(directory=str(ROOT_DIR / "migrations"), revision="head")
                check_database(db.engine, script)
                with db.engine.connect() as connection:
                    if schema_fingerprint(connection, db.metadata) != fingerprint:
                        raise RuntimeError("Repeated Alembic upgrade changed the schema")
                receipt = {
                    "format": 1,
                    "target": target.identity, "server": identity,
                    "revision": script.get_current_head(), "schema": fingerprint,
                }
                descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump(receipt, output, sort_keys=True)
                print(f"PASS: PostgreSQL 16 migrations, schema and repeat upgrade; head={script.get_current_head()}")
            finally:
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    main()
