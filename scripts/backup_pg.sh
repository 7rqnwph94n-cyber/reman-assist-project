#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-backups}"
mkdir -p "$BACKUP_DIR"

stamp=$(date +%F_%H%M%S)
base="$BACKUP_DIR/reman_pg_${stamp}.dump"

pg_dump --format=custom --no-owner --no-acl "$DATABASE_URL" > "$base"

sha256sum "$base" > "${base}.sha256"

echo "Backup created: $base"
