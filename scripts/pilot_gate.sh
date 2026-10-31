#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR"
PY_BIN="${PY_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PY_BIN" ]]; then
  echo "[pilot-gate] FAIL: Python runtime not found: $PY_BIN" >&2
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

echo "[pilot-gate] Starting pilot GO/NO-GO checks"

run_step() {
  local name="$1"
  shift
  echo "[pilot-gate] STEP: ${name}"
  "$@"
}

run_step "DB target consistency" "$PY_BIN" - <<'PY'
import os
from app import create_app

app = create_app()
with app.app_context():
    env_db = os.environ.get("DATABASE_URL", "")
    cfg_db = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    engine = app.extensions["sqlalchemy"].engine
    runtime_db = engine.url.render_as_string(hide_password=False)
    sqlite_path = os.path.abspath(engine.url.database) if engine.url.drivername.startswith("sqlite") and engine.url.database else None

    print(f"ENV_DATABASE_URL={env_db}")
    print(f"CONFIG_DATABASE_URL={cfg_db}")
    print(f"RUNTIME_DATABASE_URL={runtime_db}")
    if sqlite_path:
        print(f"RUNTIME_SQLITE_PATH={sqlite_path}")

    if env_db and cfg_db != env_db:
        raise SystemExit("FAIL: CONFIG_DATABASE_URL does not match DATABASE_URL env")
    if engine.url.drivername.startswith("sqlite"):
        if cfg_db.startswith("sqlite:////"):
            expected = os.path.abspath("/" + cfg_db.replace("sqlite:////", "", 1))
            if sqlite_path != expected:
                raise SystemExit("FAIL: runtime sqlite path does not match config absolute sqlite path")
        elif cfg_db.startswith("sqlite:///"):
            raise SystemExit("FAIL: relative sqlite DATABASE_URL detected (split-brain risk)")
    elif cfg_db != runtime_db:
        raise SystemExit("FAIL: RUNTIME_DATABASE_URL does not match app config URL")

print("PASS: DB target is consistent across env/config/runtime")
PY

run_step "Migration alignment" "$PY_BIN" scripts/migration_check.py
run_step "Schema verification" "$PY_BIN" scripts/verify_schema.py
run_step "Export smoke" "$PY_BIN" scripts/export_smoke.py
run_step "Roof test subset" "$PY_BIN" -m pytest -q tests/test_rbac_full.py tests/test_survey_idempotency.py tests/test_tenant_isolation_store_picklist.py

echo "GO: Pilot gate passed"
