from __future__ import annotations

import os
import sys

from sqlalchemy import inspect

from utils.runtime_db import get_migration_revisions


def _is_cli_invocation() -> bool:
    if os.environ.get("FLASK_RUN_FROM_CLI") or os.environ.get("FLASK_CLI"):
        return True
    argv = " ".join(sys.argv).lower()
    exe = os.path.basename(sys.argv[0]).lower()
    if exe == "flask" or " flask" in argv:
        return any(
            token in argv
            for token in (
                " db ",
                " migrate",
                " upgrade",
                " downgrade",
                " stamp",
                " revision",
                " current",
                " history",
                " heads",
            )
        )
    return False


def _is_pytest() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if "pytest" in sys.modules:
        return True
    argv = " ".join(sys.argv).lower()
    return "pytest" in argv


def startup_checks_enabled(app) -> bool:
    if app.config.get("TESTING") or _is_pytest():
        return False
    if not app.config.get("RUN_STARTUP_CHECKS", True):
        return False
    if _is_cli_invocation():
        return False
    return True


def apply_startup_mode_adjustments(app) -> None:
    if _is_cli_invocation():
        app.config["RUN_STARTUP_CHECKS"] = False


def check_schema(app, db) -> None:
    if not startup_checks_enabled(app):
        return
    if not app.config.get("CHECK_SCHEMA_ON_STARTUP", True):
        return
    if app.config.get("SKIP_SCHEMA_CHECK"):
        return

    inspector = inspect(db.engine)
    required = {
        "jobs": {
            "survey_version",
            "parts_version",
            "template_version",
            "report_revision",
        },
        "templates": {"version"},
        "attachments": {"original_filename", "uploaded_by_id"},
        "part_requirements": {
            "backorder_reason",
            "qty_received",
            "received_at",
            "received_by_id",
        },
        "store_items": {"organization_id"},
        "pick_lists": {"organization_id"},
        "pick_list_items": {"organization_id"},
    }

    missing_tables = []
    missing_columns = []
    for table, cols in required.items():
        if table not in inspector.get_table_names():
            missing_tables.append(table)
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            if col not in existing:
                missing_columns.append(f"{table}.{col}")
    if missing_tables or missing_columns:
        details = []
        if missing_tables:
            details.append(f"missing tables: {', '.join(sorted(missing_tables))}")
        if missing_columns:
            details.append(f"missing columns: {', '.join(sorted(missing_columns))}")
        msg = (
            "Database schema is behind the app code. "
            + "; ".join(details)
            + ". Run `flask db upgrade` or `python scripts/upgrade_legacy_db.py --db app.db`."
        )
        if app.config.get("STRICT_RUNTIME_MODE"):
            raise RuntimeError(msg)
        app.logger.warning("Schema check warning (non-strict mode): %s", msg)


def check_migrations(app, db) -> None:
    if not startup_checks_enabled(app):
        return
    if not app.config.get("CHECK_MIGRATIONS_ON_STARTUP", True):
        return
    if app.config.get("SKIP_SCHEMA_CHECK"):
        return

    current, heads, error = get_migration_revisions(app, db)
    if error == "migrations config missing":
        return
    if error:
        raise RuntimeError(
            "Database is missing migration metadata. "
            "Run `flask db upgrade` or `flask db stamp head` to align migrations. "
            f"Details: {error}"
        )
    if set(current) != set(heads):
        raise RuntimeError(
            f"Database migrations out of date. Current: {current}; "
            f"Expected: {heads}. Run `flask db upgrade`."
        )


def check_redis(app) -> None:
    if not startup_checks_enabled(app):
        return
    if not app.config.get("CHECK_REDIS_ON_STARTUP", True):
        return
    if not app.config.get("REQUIRE_REDIS"):
        return
    if not app.config.get("REDIS_URL"):
        raise RuntimeError(
            "REDIS_URL is required for production login throttling. "
            "Set REDIS_URL or disable REQUIRE_REDIS for non-production use."
        )
