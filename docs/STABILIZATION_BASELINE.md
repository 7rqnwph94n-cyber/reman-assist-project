# Stabilization Baseline

This checklist is the minimum known-good baseline before pilot/staging deployment.

## 1) Environment
- `FLASK_CONFIG` explicitly set (`development`/`production`)
- `APP_ENV` explicitly set (`dev`/`pilot`/`production`)
- `DATABASE_URL` explicitly set
- If SQLite in pilot/prod: absolute URL only (`sqlite:////abs/path/app.db`)
- `UPLOAD_FOLDER` set and writable
- `ENABLE_QUICKBOOKS` intentionally set (`0` or `1`)
- Run `python3 scripts/verify_env_hygiene.py` and ensure no `FAIL`

## 2) Startup Determinism
- Use canonical entrypoints only:
  - Dev: `scripts/run_dev.sh`
  - Prod: `scripts/run_prod.sh` -> `scripts/run_gunicorn.sh` -> `wsgi:app`
- Confirm startup logs show:
  - config DB URI
  - runtime DB URI
  - SQLite paths (if SQLite)
  - Alembic current/head

## 3) Schema & Migration Safety
- Run:
  - `python3 scripts/migration_check.py`
  - `python3 scripts/verify_schema.py`
- Both must pass before serving pilot traffic.

## 4) Tenant Hardening Invariants
- Required columns present:
  - `store_items.organization_id`
  - `pick_lists.organization_id`
  - `pick_list_items.organization_id`
- Tenant guard installed for tenant-owned models.
- Session identity lookup remains tenant-safe for guarded models.

## 5) Export Reliability
- Run export smoke:
  - `python3 scripts/export_smoke.py --output-dir /tmp/reman_export_smoke`
- Must produce non-empty PDF + ZIP.
- If renderer missing, install and verify with:
  - `scripts/install_pdf_renderer.sh auto`

## 6) Security/RBAC Regression Gate
- Run:
  - `python3 -m pytest -q tests/test_rbac_full.py tests/test_survey_idempotency.py tests/test_tenant_isolation_store_picklist.py`
- Must pass with active feature flags.

## 7) Backup/Restore Drill
- Backup: `python3 scripts/backup_sqlite.py --output-dir backups`
- Restore (drill env): `CONFIRM_RESTORE=1 python3 scripts/restore_sqlite.py backups/sqlite_backup_YYYYMMDD-HHMMSS`
- Verify with:
  - `python3 scripts/verify_schema.py`
  - `python3 scripts/export_smoke.py --output-dir /tmp/reman_restore_proof`

## 8) Final GO/NO-GO
- Run: `./scripts/pilot_gate.sh`
- `GO` required for pilot cutover.
