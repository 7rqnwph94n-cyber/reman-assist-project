#!/usr/bin/env python3
"""
Backup the active SQLite database and uploads directory used by the Flask app.

Usage:
  PYTHONPATH=. python3 scripts/backup_sqlite.py
  PYTHONPATH=. python3 scripts/backup_sqlite.py --output-dir backups
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import db


def _backup_uploads(upload_folder: Path, destination_tgz: Path) -> None:
    if not upload_folder.exists():
        return
    with tarfile.open(destination_tgz, "w:gz") as handle:
        handle.add(upload_folder, arcname="uploads_payload")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup active SQLite DB + uploads")
    parser.add_argument("--output-dir", default="backups", help="Backup parent directory")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        runtime_url = db.engine.url
        db_url = runtime_url.render_as_string(hide_password=False)
        if not runtime_url.drivername.startswith("sqlite") or not runtime_url.database:
            print(f"FAIL: Active database is not a file-based SQLite URL: {db_url}")
            return 1
        db_file = Path(os.path.abspath(runtime_url.database))
        if not db_file.exists():
            print(f"FAIL: Active SQLite database file not found: {db_file}")
            return 1

        upload_folder = Path(str(app.config.get("UPLOAD_FOLDER") or "")).resolve()
        backup_root = Path(args.output_dir).resolve()
        backup_root.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        artifact_dir = backup_root / f"sqlite_backup_{stamp}"
        artifact_dir.mkdir(parents=True, exist_ok=False)

        db_copy = artifact_dir / "app.db"
        shutil.copy2(db_file, db_copy)

        uploads_archive = artifact_dir / "uploads.tgz"
        _backup_uploads(upload_folder, uploads_archive)

        manifest = {
            "created_at": stamp,
            "database_url": db_url,
            "active_sqlite_path": str(db_file),
            "backup_db_file": str(db_copy),
            "upload_folder": str(upload_folder),
            "uploads_archive": str(uploads_archive) if uploads_archive.exists() else None,
        }
        (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        print("PASS: SQLite backup complete")
        print(f"ACTIVE_DB_URL={db_url}")
        print(f"ACTIVE_DB_PATH={db_file}")
        print(f"BACKUP_DIR={artifact_dir}")
        print(f"BACKUP_DB_FILE={db_copy}")
        if uploads_archive.exists():
            print(f"BACKUP_UPLOADS_FILE={uploads_archive}")
        else:
            print("BACKUP_UPLOADS_FILE=SKIPPED (upload folder missing)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
