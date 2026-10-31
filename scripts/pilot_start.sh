#!/usr/bin/env bash
set -euo pipefail

required=(FLASK_CONFIG APP_ENV DATABASE_URL SECRET_KEY UPLOAD_FOLDER LOG_FILE)
missing=()
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    missing+=("$v")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing env vars: ${missing[*]}" >&2
  exit 1
fi

mkdir -p "$UPLOAD_FOLDER"
if [[ ! -w "$UPLOAD_FOLDER" ]]; then
  echo "UPLOAD_FOLDER not writable: $UPLOAD_FOLDER" >&2
  exit 1
fi

python -m flask --app app:create_app db upgrade

if [[ -n "${ADMIN_EMAIL:-}" && -n "${ADMIN_PASSWORD:-}" ]]; then
  python -m flask --app app:create_app create-admin -u "$ADMIN_EMAIL" -p "$ADMIN_PASSWORD" --update
else
  echo "ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping admin creation"
fi

PORT=${PORT:-5001}
exec scripts/run_gunicorn.sh "$PORT"
