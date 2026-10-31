#!/usr/bin/env python3
"""
Preflight migration check using the same app config/DB target as runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import db


def main() -> int:
    app = create_app()
    with app.app_context():
        migrations_dir = os.path.join(app.root_path, "migrations")
        alembic_ini = os.path.join(migrations_dir, "alembic.ini")
        if not os.path.isdir(migrations_dir) or not os.path.exists(alembic_ini):
            print("FAIL: migrations config missing")
            return 1

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
            print(f"FAIL: could not read alembic_version ({exc})")
            return 2

        print(f"ALEMBIC_CURRENT={current}")
        print(f"ALEMBIC_HEAD={heads}")
        if set(current) != set(heads):
            print("FAIL: migration mismatch")
            return 3

    print("PASS: migrations aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
