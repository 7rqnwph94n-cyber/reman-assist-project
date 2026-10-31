#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${RESTORE_DATABASE_URL:-}" ]]; then
  echo "RESTORE_DATABASE_URL is required" >&2
  exit 1
fi
if [[ "${CONFIRM_RESTORE:-}" != "1" ]]; then
  echo "CONFIRM_RESTORE=1 is required" >&2
  exit 1
fi

backup_file="${1:-}"
if [[ -z "$backup_file" ]]; then
  echo "Usage: restore_pg.sh /path/to/backup.dump" >&2
  exit 1
fi
if [[ ! -f "$backup_file" ]]; then
  echo "Backup file not found: $backup_file" >&2
  exit 1
fi

count=$(psql "$RESTORE_DATABASE_URL" -Atc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")
if [[ "$count" != "0" ]]; then
  echo "Target DB is not empty (public tables: $count). Aborting." >&2
  exit 1
fi

pg_restore --no-owner --no-acl --dbname="$RESTORE_DATABASE_URL" "$backup_file"

echo "Restore complete: $backup_file"
