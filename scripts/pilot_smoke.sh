#!/usr/bin/env bash
set -euo pipefail

python3 -m pytest tests/test_pilot_smoke.py

if [[ "${PILOT_REQUIRE_PDF:-}" == "1" ]]; then
  scripts/check_pdf_extractor.sh
fi

if [[ "${PILOT_RESTORE_DRILL:-}" == "1" ]]; then
  if [[ -z "${DATABASE_URL:-}" || -z "${UPLOAD_FOLDER:-}" || -z "${RESTORE_DATABASE_URL:-}" || -z "${RESTORE_UPLOAD_FOLDER:-}" ]]; then
    echo "Restore drill requires DATABASE_URL, UPLOAD_FOLDER, RESTORE_DATABASE_URL, RESTORE_UPLOAD_FOLDER" >&2
    exit 1
  fi
  BACKUP_DIR="${BACKUP_DIR:-backups}"
  mkdir -p "$BACKUP_DIR"
  scripts/backup_pg.sh
  scripts/backup_uploads.sh
  latest_db=$(ls -t "$BACKUP_DIR"/reman_pg_*.dump | head -n 1)
  latest_uploads=$(ls -t "$BACKUP_DIR"/reman_uploads_*.tgz | head -n 1)
  if [[ -z "${latest_db:-}" || -z "${latest_uploads:-}" ]]; then
    echo "Backup files not found in $BACKUP_DIR" >&2
    exit 1
  fi
  export RESTORE_DATABASE_URL
  export CONFIRM_RESTORE=1
  scripts/restore_pg.sh "$latest_db"
  export UPLOAD_FOLDER="$RESTORE_UPLOAD_FOLDER"
  export CONFIRM_RESTORE=1
  scripts/restore_uploads.sh "$latest_uploads"
fi

scripts/pilot_validate.py
