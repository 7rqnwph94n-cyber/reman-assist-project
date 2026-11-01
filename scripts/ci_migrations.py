#!/usr/bin/env python3
"""Migrate a new, guarded disposable SQLite DB and verify its actual revision."""

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.db_safety import (
    allow_database,
    assert_engine_database,
    forget_database,
    install_connection_guards,
)
from scripts.migration_check import check_database, check_graph, migration_script


def main() -> None:
    install_connection_guards()
    script = migration_script()
    check_graph(script)
    with TemporaryDirectory(prefix="reman-ci-migrations-") as directory:
        root = Path(directory).resolve()
        database = allow_database(root / "migration.db", root)
        uri = f"sqlite:///{database}"
        # Set before importing app/config; never use inherited runtime targets.
        os.environ.update({
            "FLASK_CONFIG": "testing",
            "FLASK_ENV": "development",
            "APP_ENV": "test",
            "DATABASE_URL": uri,
            "SECRET_KEY": "disposable-migration-check-only",
            "UPLOAD_FOLDER": str(root / "uploads"),
            "LOG_FILE": str(root / "app.log"),
            "REDIS_URL": "",
            "ENABLE_QUICKBOOKS": "0",
        })

        from flask import Flask
        from flask_migrate import upgrade
        from sqlalchemy import text
        from app import create_app
        from config import TestingConfig
        from models import db

        app = create_app(
            TestingConfig, app_instance=Flask("app"),
            config_overrides={"SQLALCHEMY_DATABASE_URI": uri, "LOG_FILE": None},
        )
        try:
            with app.app_context():
                assert_engine_database(db.engine, uri)
                with db.engine.connect() as connection:
                    databases = [tuple(row) for row in connection.execute(text("PRAGMA database_list"))]
                    assert databases == [(0, "main", str(database))]
                    assert connection.execute(text(
                        "SELECT count(*) FROM sqlite_master WHERE type='table'"
                    )).scalar_one() == 0
                print(f"DISPOSABLE_ENGINE_VERIFIED={db.engine.url}")
                upgrade(directory=str(ROOT_DIR / "migrations"), revision="head")
                check_database(db.engine, script)
                print("PASS: fresh disposable database migrated to the expected head")
        finally:
            with app.app_context():
                db.session.remove()
                for engine in db.engines.values():
                    engine.dispose()
            forget_database(database)


if __name__ == "__main__":
    main()
