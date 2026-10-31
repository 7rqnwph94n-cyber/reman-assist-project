# Reman Assistant - Setup, Deploy, and Operations (Single Guide)

This is the single source of truth for installing, migrating, and running Reman Assistant.
If you are not sure what to do, start at the top and follow the steps in order.

## 0) What this app does (plain English)
- A Job Pack is the single record for each engine.
- Techs fill out the strip survey and measurements.
- The survey creates the BOM (parts list) for the job.
- Office prices and orders parts, stores receives, build completes.
- Everything is tracked with attachments and audit events.

## 1) Quick Start (Dev / SQLite)

Goal: run locally with test data.

1) Create a venv and install deps
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Create DB schema
```
python -m flask --app app:create_app db upgrade
```

3) Seed sample data
```
flask --app app:create_app seed --users 4
```

4) Run the app
```
./scripts/run_dev.sh
```

Open: http://127.0.0.1:5001

Default logins:
- admin@example.com / Password123!
- office@example.com / Password123!
- technician@example.com / Password123!
- stores@example.com / Password123!

## 2) Production Setup (Postgres + Redis)

Goal: stable, multi-user production.

1) Environment variables (required)
- Use `.env.sample` as a reference list (export variables in your shell or service file).
- `FLASK_ENV=production`
- `APP_ENV=production`
- `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/reman`
- `SECRET_KEY=your-long-secret`
- `REDIS_URL=redis://host:6379/0`
- `REQUIRE_REDIS=1`
- `UPLOAD_FOLDER=/path/to/uploads`
- `LOG_FILE=/path/to/logs/app.log`
- `LOG_LEVEL=INFO` (optional)
- `LOG_FORMAT=json` (optional, structured logs)

Important: `UPLOAD_FOLDER` is required in production and must point to a persistent, backed-up location.

2) Install dependencies
```
pip install -r requirements.txt
```

3) Run migrations
```
python -m flask --app app:create_app db upgrade
```

4) Run the app (recommended WSGI entrypoint)
```
# gunicorn example

gunicorn wsgi:app -b 0.0.0.0:5001
```

## 3) Deploy Checklist (short version)

Do this every deploy:

1) Backup DB
- SQLite: `PYTHONPATH=. python3 scripts/backup_sqlite.py`
- Postgres: `pg_dump $DATABASE_URL > backup_$(date +%F).sql`

2) Apply migrations
```
python -m flask --app app:create_app db upgrade
```

3) Start / restart service
- systemd: `sudo systemctl restart reman`
- gunicorn: `gunicorn wsgi:app -b 0.0.0.0:5001`

4) Smoke checks
- `curl http://127.0.0.1:5001/health`
- Login as admin, open a job, open survey, open parts

## 4) Migrations (easy mode)

Normal upgrade:
```
python -m flask --app app:create_app db upgrade
```

Check heads:
```
python -m flask --app app:create_app db heads
```

If multiple heads:
```
python -m flask --app app:create_app db merge <head1> <head2> -m "merge heads"
python -m flask --app app:create_app db upgrade
```

If DB already matches but migration complains:
```
python -m flask --app app:create_app db stamp head
```

## 5) Reports and Exports (Job Pack)

- HTML report: `/jobs/<id>/report`
- PDF: `/jobs/<id>/report.pdf`
- ZIP pack: `/jobs/<id>/export.zip`

WeasyPrint dependencies (macOS):
```
brew install pango cairo gobject-introspection libffi gdk-pixbuf
```

If you see `libgobject-2.0-0` errors on macOS:
```
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib:$DYLD_LIBRARY_PATH"
```

Optional Playwright fallback:
```
pip install playwright
python -m playwright install chromium
```

Key photos in PDF:
- Enabled by default for internal view (limited count/size).
- Control via `REPORT_EMBED_IMAGES`, `REPORT_MAX_IMAGE_EMBEDS`, `REPORT_MAX_IMAGE_EMBED_MB`.

## 6) Commercial Deployment Stance (early sales)
- Single-tenant per client: one DB + one uploads folder per customer.
- This avoids cross-client data risk until multi-tenant support exists.
- Keep a per-client deployment checklist with their `DATABASE_URL` + `UPLOAD_FOLDER`.

## 6) Backup / Restore (SQLite)

Backup:
```
PYTHONPATH=. python3 scripts/backup_sqlite.py
```

2Restore:
```
PYTHONPATH=. python3 scripts/restore_sqlite.py <backup_file>
```

## 7) Testing

Unit/integration:
```
python -m pytest
```

E2E (Playwright):
```
python -m pytest e2e
```

## 8) Common Problems (fast fixes)

- "No such command 'db'":
  - Use `python -m flask --app app:create_app db upgrade`

- App wont start:
  - Check `LOG_FILE` or `journalctl`
  - Verify `DATABASE_URL` and `SECRET_KEY`

- Redis errors in prod:
  - Check `REDIS_URL` and set `REQUIRE_REDIS=1`

## 9) Repository Layout (high level)
- `app.py` Flask factory + routes
- `wsgi.py` WSGI entrypoint (gunicorn/systemd)
- `models.py` SQLAlchemy models
- `services/` Domain logic (BOM, reports, exports)
- `templates/` Jinja2 UI
- `static/` CSS/JS assets
- `uploads/` User uploads (git ignored)

## 10) Who to call
If anything feels weird, call Rich. This app is shop-floor critical.

## 11) Professionalization Checklist (work through in order)

Check items off as we go.

### A) Ops & Runtime
- [ ] Add `/ready` and `/version` endpoints
- [ ] Structured JSON logs + request ID per request
- [ ] Single config module with dev/test/prod defaults

### B) Data Integrity
- [ ] Add DB constraints (unique job_number/job_pack_id)
- [ ] Add FK cascade rules for attachments/parts/surveys
- [x] Add migration tests in CI

### C) Security
- [x] Rate-limit login and add backoff/lockouts
- [ ] Upload hardening: size caps + signature checks
- [ ] Audit log for every state change and costing apply

### D) Reliability & Workflow
- [ ] Enforce a strict job status state machine
- [ ] BOM regen is idempotent + versioned snapshots
- [ ] Background jobs for PDF/ZIP exports

### E) Performance
- [ ] N+1 audit for heavy pages (selectinload/joinedload)
- [ ] Pagination on any list > 100 rows (verify all)

### F) Testing & CI
- [ ] CI pipeline: pytest + lint + migrations check
- [ ] Workflow tests: job → survey → BOM → parts → picklist → build

### G) UX (no style changes)
- [ ] “Next step” helper text per job status
- [ ] Bulk actions in procurement/parts where needed
