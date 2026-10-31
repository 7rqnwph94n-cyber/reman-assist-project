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

PORT="${1:-5001}"
WORKERS="${WORKERS:-3}"
TIMEOUT="${TIMEOUT:-120}"

exec gunicorn -w "$WORKERS" --timeout "$TIMEOUT" -b "0.0.0.0:${PORT}" "wsgi:app"
