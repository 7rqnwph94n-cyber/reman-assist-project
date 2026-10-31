#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

export APP_ENV=dev
export FLASK_ENV=development
export FLASK_CONFIG=development

PORT="${PORT:-5001}"
exec python3 -m flask --app wsgi:app run --host 0.0.0.0 --port "$PORT" --debug
