#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${UPLOAD_FOLDER:-}" ]]; then
  echo "UPLOAD_FOLDER is required" >&2
  exit 1
fi
if [[ "${CONFIRM_RESTORE:-}" != "1" ]]; then
  echo "CONFIRM_RESTORE=1 is required" >&2
  exit 1
fi

backup_file="${1:-}"
if [[ -z "$backup_file" ]]; then
  echo "Usage: restore_uploads.sh /path/to/uploads_backup.tgz" >&2
  exit 1
fi
if [[ ! -f "$backup_file" ]]; then
  echo "Backup file not found: $backup_file" >&2
  exit 1
fi

mkdir -p "$UPLOAD_FOLDER"
tar -xzf "$backup_file" -C "$UPLOAD_FOLDER"

echo "Uploads restored: $backup_file"
