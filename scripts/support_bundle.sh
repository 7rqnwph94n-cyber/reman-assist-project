#!/usr/bin/env bash
set -euo pipefail

stamp=$(date +%F_%H%M%S)
workdir=$(mktemp -d)

summary="$workdir/summary.txt"
{
  echo "Timestamp: $stamp"
  echo "Host: $(hostname)"
  echo "PWD: $(pwd)"
  echo "Git: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "APP_ENV=${APP_ENV:-}"
  echo "FLASK_CONFIG=${FLASK_CONFIG:-}"
  echo "UPLOAD_FOLDER=${UPLOAD_FOLDER:-}"
  echo "LOG_FILE=${LOG_FILE:-}"
} > "$summary"

# Redacted env summary
env | grep -E 'APP_ENV|FLASK_ENV|FLASK_CONFIG|UPLOAD_FOLDER|LOG_FILE|LOG_LEVEL|LOG_FORMAT|REDIS_URL|PDF_EXTRACTOR_PROFILES_DIR' \
  | sed -E 's/(REDIS_URL=).*/\1[redacted]/' >> "$summary" || true

# Alembic version
python3 - <<'PY' > "$workdir/alembic_version.txt" 2>/dev/null || true
from app import app as flask_app
from models import db
from sqlalchemy import text
with flask_app.app_context():
    v = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar()
    dbver = db.session.execute(text('SELECT sqlite_version()')).scalar() if db.engine.dialect.name == 'sqlite' else db.session.execute(text('SELECT version()')).scalar()
    print(v)
    print(dbver)
PY

# App logs
if [[ -n "${LOG_FILE:-}" && -f "${LOG_FILE:-}" ]]; then
  tail -n 200 "$LOG_FILE" > "$workdir/app.log.tail" || true
fi

# Uploads disk usage
if [[ -n "${UPLOAD_FOLDER:-}" && -d "${UPLOAD_FOLDER:-}" ]]; then
  du -sh "$UPLOAD_FOLDER" > "$workdir/uploads_disk_usage.txt" || true
fi

# Proxy logs (best effort)
for f in /var/log/nginx/access.log /var/log/nginx/error.log; do
  if [[ -f "$f" ]]; then
    tail -n 200 "$f" > "$workdir/$(basename "$f").tail" || true
  fi
done

bundle="/tmp/reman_support_${stamp}.tgz"
tar -czf "$bundle" -C "$workdir" .

echo "Support bundle: $bundle"
