# Pilot Checklist (Reman Assistant)

Use this as a go/no-go list for a 5-terminal pilot.

Pre-pilot
- Confirm data backup completed and verified.
- Decide production DB (Postgres recommended for pilot).
- Confirm server hostname/IP and TLS plan (HTTPS recommended).

Deployment
- Set env: `FLASK_ENV=production`, `DATABASE_URL`, `SECRET_KEY`, `LOG_FILE`, `REDIS_URL`.
- Run migrations: `flask db upgrade`.
- Start service via Gunicorn/systemd (not `python app.py`).
- Confirm Redis is running (rate-limit + future session storage).
- Verify `/health` returns `{"status":"ok","db":"ok"}`.

Data + Roles
- Admin user created and tested login.
- Office, Technician, Stores users created and assigned.
- At least one template exists with measurements configured.
- Section images uploaded (if used) and verified view.

File Storage
- `UPLOAD_FOLDER` is on server disk or shared storage.
- Attachment upload/download works.
- Storage location has backup coverage.

Workflow Validation
- Create job → assign technician → pre-survey saved.
- Survey completed → BOM created → status moves to Office.
- Parts updated (procurement status + approvals).
- Pick list issued and visible to Stores.
- Attachment uploaded and visible in Job Pack.
- Audit log entries appear for key actions.

Performance
- Job list loads with 500+ jobs without timeout.
- Survey page loads with 300+ lines within 3-5s.
- Parts page loads with 300+ lines within 3-5s.

Go/No-Go
- No 500 errors during the above workflow.
- Audit log captures: login/logout, survey complete, parts update, attachment upload.
- DB and file backups confirmed.
