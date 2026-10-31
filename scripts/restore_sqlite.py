#!/usr/bin/env python3
"""
Restore the active SQLite database and uploads directory from backup artifact.

Usage:
  PYTHONPATH=. python3 scripts/restore_sqlite.py backups/sqlite_backup_YYYYMMDD-HHMMSS
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import db


def _confirm(prompt: str, auto_yes: bool) -> bool:
    if auto_yes or os.environ.get("CONFIRM_RESTORE") == "1":
        return True
    answer = input(prompt).strip().lower()
    return answer == "y"


def _restore_uploads(uploads_tgz: Path, target_upload_folder: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="restore_uploads_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        with tarfile.open(uploads_tgz, "r:gz") as handle:
            try:
                handle.extractall(path=tmpdir_path, filter="data")
            except TypeError:
                handle.extractall(path=tmpdir_path)
        payload = tmpdir_path / "uploads_payload"
        if not payload.exists() or not payload.is_dir():
            raise RuntimeError(f"Invalid uploads archive format in {uploads_tgz}")

        if target_upload_folder.exists():
            shutil.rmtree(target_upload_folder)
        target_upload_folder.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(payload, target_upload_folder)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore active SQLite DB + uploads")
    parser.add_argument("backup_dir", help="Path to sqlite backup directory")
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir).resolve()
    if not backup_dir.exists() or not backup_dir.is_dir():
        print(f"FAIL: Backup directory not found: {backup_dir}")
        return 1

    backup_db = backup_dir / "app.db"
    if not backup_db.exists():
        print(f"FAIL: Missing backup DB file: {backup_db}")
        return 1

    uploads_tgz = backup_dir / "uploads.tgz"

    app = create_app()
    with app.app_context():
        runtime_url = db.engine.url
        db_url = runtime_url.render_as_string(hide_password=False)
        if not runtime_url.drivername.startswith("sqlite") or not runtime_url.database:
            print(f"FAIL: Active database is not a file-based SQLite URL: {db_url}")
            return 1

        active_db = Path(os.path.abspath(runtime_url.database))
        active_db.parent.mkdir(parents=True, exist_ok=True)
        upload_folder = Path(str(app.config.get("UPLOAD_FOLDER") or "")).resolve()

        print(f"ACTIVE_DB_URL={db_url}")
        print(f"ACTIVE_DB_PATH={active_db}")
        print(f"ACTIVE_UPLOAD_FOLDER={upload_folder}")
        print(f"BACKUP_DIR={backup_dir}")

        if not _confirm(
            f"Restore {backup_db} -> {active_db} and uploads -> {upload_folder}? This overwrites current data. [y/N]: ",
            args.yes,
        ):
            print("Aborted.")
            return 1

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety_dir = backup_dir / f"pre_restore_snapshot_{stamp}"
        safety_dir.mkdir(parents=True, exist_ok=True)

        if active_db.exists():
            shutil.copy2(active_db, safety_dir / "active_app_before_restore.db")

        if upload_folder.exists() and upload_folder.is_dir():
            with tarfile.open(safety_dir / "active_uploads_before_restore.tgz", "w:gz") as handle:
                handle.add(upload_folder, arcname="uploads_payload")

        shutil.copy2(backup_db, active_db)

        if uploads_tgz.exists():
            _restore_uploads(uploads_tgz, upload_folder)
            uploads_msg = str(uploads_tgz)
        else:
            uploads_msg = "SKIPPED (uploads.tgz missing in backup artifact)"

        print("PASS: Restore complete")
        print(f"RESTORED_DB_FILE={active_db}")
        print(f"RESTORED_UPLOADS={uploads_msg}")
        print(f"SAFETY_SNAPSHOT={safety_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
