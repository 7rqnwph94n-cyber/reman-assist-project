#!/usr/bin/env bash
set -euo pipefail

if [[ "${1-}" == "--help" ]]; then
  echo "Usage: scripts/postgres_verify.sh"
  echo "Requires DATABASE_URL to be set to Postgres URL."
  exit 0
fi

if [[ -z "${DATABASE_URL-}" ]]; then
  echo "DATABASE_URL is not set. Example:"
  echo "  export DATABASE_URL=\"postgresql+psycopg://dev:699669@localhost:5432/reman\""
  exit 1
fi

python scripts/db_integrity_check.py

echo "Running migrations..."
python -m flask --app app:create_app db upgrade

echo "Done. Now manually smoke test:"
cat <<'EOF'
- Login
- Job list
- Survey (paged)
- Parts (paged)
- Report HTML/PDF/ZIP
EOF
