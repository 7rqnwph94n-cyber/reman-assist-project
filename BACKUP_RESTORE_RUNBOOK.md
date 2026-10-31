# Backup & Restore Runbook

## Scope
- This runbook covers SQLite backup/restore using the **active app DB target** (no hardcoded `app.db`).
- For Postgres, keep using `scripts/backup_pg.sh` and `scripts/restore_pg.sh`.

## Preconditions
- Run from repo root.
- `DATABASE_URL` and `UPLOAD_FOLDER` point to the environment you intend to back up.
- For pilot/prod, `DATABASE_URL` must be explicit and valid.

## Backup (SQLite)
1. Validate DB target and schema:
   ```bash
   PYTHONPATH=. python3 scripts/verify_schema.py
   ```
2. Create backup artifact:
   ```bash
   PYTHONPATH=. python3 scripts/backup_sqlite.py --output-dir backups
   ```
3. Record artifact path printed as `BACKUP_DIR=...`.

Backup artifact contents:
- `app.db`
- `uploads.tgz` (if upload folder exists)
- `manifest.json` (resolved DB URL/path and metadata)

## Restore (SQLite)
1. Stop app writes (maintenance window).
2. Restore from artifact:
   ```bash
   PYTHONPATH=. python3 scripts/restore_sqlite.py backups/sqlite_backup_YYYYMMDD-HHMMSS --yes
   ```
3. Re-run migrations/safety checks:
   ```bash
   python3 scripts/migration_check.py
   PYTHONPATH=. python3 scripts/verify_schema.py
   ```
4. Run export proof:
   ```bash
   PYTHONPATH=. python3 scripts/export_smoke.py --output-dir /tmp/reman_restore_proof
   ```

The restore script also creates a pre-restore safety snapshot in the backup artifact directory.

## Restore Drill (Proof Artifact)
1. Restore a recent backup to a test environment.
2. Generate proof artifact:
   ```bash
   python3 - <<'PY'
from app import create_app
from models import Job
app = create_app()
with app.app_context():
    print(f"RESTORE_JOB_COUNT={Job.query.count()}")
PY
   PYTHONPATH=. python3 scripts/export_smoke.py --output-dir /tmp/reman_restore_proof
   ls -lh /tmp/reman_restore_proof
   ```
3. Archive outputs from `/tmp/reman_restore_proof` (PDF + ZIP) with the drill ticket.

## Success Criteria
- `scripts/verify_schema.py` prints `PASS`.
- `scripts/migration_check.py` prints `PASS: migrations aligned`.
- `scripts/export_smoke.py` prints `PASS: export smoke complete` and writes non-empty PDF/ZIP.

## Failure Handling
- If restore verification fails, use `pre_restore_snapshot_*` from the artifact to roll back DB/uploads.
- Do not reopen the environment for writes until verification passes.
