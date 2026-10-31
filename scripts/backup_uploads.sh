#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${UPLOAD_FOLDER:-}" ]]; then
  echo "UPLOAD_FOLDER is required" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-backups}"
mkdir -p "$BACKUP_DIR"

stamp=$(date +%F_%H%M%S)
base="$BACKUP_DIR/reman_uploads_${stamp}.tgz"

tar -czf "$base" -C "$UPLOAD_FOLDER" .
sha256sum "$base" > "$base.sha256"

echo "Uploads backup created: $base"
