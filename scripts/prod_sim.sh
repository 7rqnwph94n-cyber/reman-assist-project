#!/usr/bin/env bash
set -euo pipefail

# Production-like simulation for local verification.

export APP_ENV=production
export FLASK_ENV=production
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://dev:699669@localhost:5432/reman}"
export SECRET_KEY="${SECRET_KEY:-change-me-prod}"
export LOG_FILE="${LOG_FILE:-instance/app.log}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export RUN_STARTUP_CHECKS="${RUN_STARTUP_CHECKS:-1}"
export CHECK_SCHEMA_ON_STARTUP="${CHECK_SCHEMA_ON_STARTUP:-1}"
export CHECK_MIGRATIONS_ON_STARTUP="${CHECK_MIGRATIONS_ON_STARTUP:-1}"
export CHECK_REDIS_ON_STARTUP="${CHECK_REDIS_ON_STARTUP:-1}"

python -m flask --app app:create_app db upgrade

if command -v brew >/dev/null 2>&1; then
  brew services start redis >/dev/null 2>&1 || true
fi

python3 app.py
