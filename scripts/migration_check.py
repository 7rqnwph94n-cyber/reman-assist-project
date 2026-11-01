#!/usr/bin/env python3
"""
Check the migration graph alone, or verify the configured runtime DB revision.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def migration_script() -> ScriptDirectory:
    migrations_dir = ROOT_DIR / "migrations"
    cfg = AlembicConfig(str(migrations_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(migrations_dir))
    return ScriptDirectory.from_config(cfg)


def check_graph(script: ScriptDirectory) -> None:
    revisions = list(script.walk_revisions())
    heads = script.get_heads()
    print(f"ALEMBIC_HEAD={heads}")
    print(f"ALEMBIC_REVISION_COUNT={len(revisions)}")
    if not revisions or len(heads) != 1:
        raise RuntimeError("Expected a non-empty migration graph with exactly one head")


def check_database(engine, script: ScriptDirectory) -> None:
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    heads = set(script.get_heads())
    print(f"ALEMBIC_CURRENT={sorted(current)}")
    print(f"ALEMBIC_HEAD={sorted(heads)}")
    if not current or current != heads:
        raise RuntimeError("Database revision does not match the migration head")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--heads-only", action="store_true",
        help="Validate the graph and single head without importing the app or connecting to a DB",
    )
    args = parser.parse_args(argv)
    try:
        script = migration_script()
        check_graph(script)
        if args.heads_only:
            print("PASS: migration graph validated (no database connection)")
            return 0

        # Keep the existing read-only runtime alignment check for support scripts.
        from app import create_app
        from models import db

        app = create_app()
        with app.app_context():
            check_database(db.engine, script)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print("PASS: migrations aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
