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

export APP_ENV=production
export FLASK_ENV=production
export FLASK_CONFIG=production

if [[ -z "${SECRET_KEY:-}" && -z "${FLASK_SECRET_KEY:-}" ]]; then
  echo "ERROR: SECRET_KEY (or FLASK_SECRET_KEY) is required for production." >&2
  exit 1
fi

if [[ -z "${REDIS_URL:-}" ]]; then
  echo "ERROR: REDIS_URL is required for production login throttling." >&2
  exit 1
fi

PORT="${PORT:-5001}"
exec scripts/run_gunicorn.sh "$PORT"
