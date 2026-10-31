#!/usr/bin/env python3
"""
Verify migration alignment and required schema columns for pilot-safe startup.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import db


def _sqlite_path(db_url: str) -> str | None:
    if not db_url.startswith("sqlite:"):
        return None
    if db_url.startswith("sqlite:////"):
        return os.path.abspath("/" + db_url.replace("sqlite:////", "", 1))
    if db_url.startswith("sqlite:///"):
        rel = db_url.replace("sqlite:///", "", 1)
        return os.path.abspath(rel)
    return None


def _migration_state(app) -> tuple[list[str], list[str], str | None]:
    migrations_dir = os.path.join(app.root_path, "migrations")
    alembic_ini = os.path.join(migrations_dir, "alembic.ini")
    if not os.path.isdir(migrations_dir) or not os.path.exists(alembic_ini):
        return [], [], "migrations config missing"

    cfg = AlembicConfig(alembic_ini)
    cfg.set_main_option("script_location", migrations_dir)
    script = ScriptDirectory.from_config(cfg)
    heads = sorted(set(script.get_heads()))

    try:
        with db.engine.connect() as conn:
            current = sorted(
                set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all())
            )
    except Exception as exc:
        return [], heads, f"could not read alembic_version: {exc}"
    return current, heads, None


def main() -> int:
    app = create_app()
    errors: list[str] = []

    required = {
        "jobs": {"survey_version", "parts_version", "template_version", "report_revision"},
        "templates": {"version"},
        "attachments": {"original_filename", "uploaded_by_id"},
        "part_requirements": {"backorder_reason", "qty_received", "received_at", "received_by_id"},
        "store_items": {"organization_id"},
        "pick_lists": {"organization_id"},
        "pick_list_items": {"organization_id"},
    }

    with app.app_context():
        db_url = db.engine.url.render_as_string(hide_password=False)
        print(f"DB_URL={db_url}")
        sqlite_path = _sqlite_path(db_url)
        if sqlite_path:
            print(f"SQLITE_PATH={sqlite_path}")

        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())
        for table, cols in required.items():
            if table not in table_names:
                errors.append(f"missing table: {table}")
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col in sorted(cols):
                if col not in existing_cols:
                    errors.append(f"missing column: {table}.{col}")

        current, heads, mig_error = _migration_state(app)
        if mig_error:
            errors.append(f"migration check failed: {mig_error}")
            print(f"ALEMBIC_CURRENT=UNKNOWN ({mig_error})")
            print(f"ALEMBIC_HEAD={heads or ['UNKNOWN']}")
        else:
            print(f"ALEMBIC_CURRENT={current}")
            print(f"ALEMBIC_HEAD={heads}")
            if set(current) != set(heads):
                errors.append(f"migration mismatch: current={current} head={heads}")

    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
