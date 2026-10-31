# Tenant Hardening Runbook (StoreItem / PickList / PickListItem)

This runbook operationalizes row-level tenant isolation migration and validation.

## 1) Pre-flight checks

Run from repo root:

```bash
pwd
python3 --version
python3 -m flask --app app:create_app db current
python3 -m flask --app app:create_app db heads
```

Success criteria:
- `db current` returns a revision (not empty).
- `db heads` returns exactly one head revision.

Detect backend:

```bash
python3 - <<'PY'
from app import create_app
from models import db
app = create_app()
with app.app_context():
    print(db.engine.dialect.name)
    print(db.engine.url)
PY
```

Expected backend values:
- `sqlite`
- `postgresql`
- `mysql`

## 2) Backup before migration

### SQLite

```bash
cp app.db "app.db.backup.$(date +%Y%m%d_%H%M%S)"
```

### PostgreSQL

```bash
pg_dump "$DATABASE_URL" > "backup_$(date +%Y%m%d_%H%M%S).sql"
```

### MySQL

```bash
mysqldump --databases your_db_name > "backup_$(date +%Y%m%d_%H%M%S).sql"
```

## 3) Apply migration

```bash
python3 -m flask --app app:create_app db upgrade
python3 -m flask --app app:create_app db current
```

Success criteria:
- Upgrade completes with no exception.
- `db current` matches head.

## 4) Run migration verification checks

Read-only verification:

```bash
PYTHONPATH=. python3 scripts/verify_tenant_hardening.py
```

Uniqueness write-probe (safe in rollback transaction):

```bash
PYTHONPATH=. python3 scripts/verify_tenant_hardening.py --exercise-unique
```

Success criteria:
- Script ends with `RESULT: PASS (all checks passed)`.

## 5) Run security tests

```bash
pytest -q tests/test_tenant_isolation_store_picklist.py
pytest -q
```

Success criteria:
- Targeted test file passes.
- Full suite passes (or only expected skips).

## 6) Rollback / recovery plan

### Option A: Fast database restore (safest)

Use your backup from step 2:
- SQLite: replace `app.db` with backup copy.
- Postgres/MySQL: restore dump.

### Option B: Alembic downgrade (only if no incompatible app writes occurred)

```bash
python3 -m flask --app app:create_app db downgrade bb8c9d0e1f2a
```

Then re-run `db current` and smoke tests.

## 7) DB locking/index notes by backend

### SQLite
- `batch_alter_table` may rebuild tables and lock writes for migration duration.
- Perform migration in maintenance window.

### PostgreSQL
- `ALTER TABLE` and constraint changes take table locks; typically short but can block concurrent writes.
- Schedule during low-traffic window.

### MySQL
- Depending on engine/version, `ALTER TABLE` may copy table or lock writes.
- Use maintenance window; verify engine supports online DDL if required.

## 8) Final production sign-off checklist

- [ ] Backup completed
- [ ] `db upgrade` successful
- [ ] `verify_tenant_hardening.py` PASS
- [ ] `--exercise-unique` PASS (staging required before prod)
- [ ] `pytest -q` PASS
- [ ] Post-deploy smoke test for Stores/Picklists complete
