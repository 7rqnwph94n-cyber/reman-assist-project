#!/usr/bin/env bash
set -euo pipefail

required=(SIM_DATABASE_URL SIM_UPLOAD_FOLDER)
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

export APP_ENV=production
export FLASK_CONFIG=production
export DEBUG=0
export DATABASE_URL="$SIM_DATABASE_URL"
export UPLOAD_FOLDER="$SIM_UPLOAD_FOLDER"
export SECRET_KEY="${SECRET_KEY:-simulation-secret}"
export LOG_FILE="${LOG_FILE:-instance/app.log}"

mkdir -p "$UPLOAD_FOLDER"
python -m flask --app app:create_app db upgrade

if [[ -n "${ADMIN_EMAIL:-}" && -n "${ADMIN_PASSWORD:-}" ]]; then
  python -m flask --app app:create_app create-admin -u "$ADMIN_EMAIL" -p "$ADMIN_PASSWORD" --update
fi

scripts/pilot_smoke.sh
