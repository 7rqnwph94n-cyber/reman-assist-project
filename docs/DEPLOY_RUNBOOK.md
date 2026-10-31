# Pilot Deploy Runbook (Single Tenant)

## Golden path
1) Create `.env` from `.env.sample`
2) Install deps: `pip install -r requirements.txt`
3) Migrate: `python -m flask --app app:create_app db upgrade`
4) Create admin: `python -m flask --app app:create_app create-admin -u admin@example.com`
5) Start: `scripts/pilot_start.sh`

## Required env
- `FLASK_CONFIG=production`
- `APP_ENV=production`
- `DATABASE_URL=postgresql+psycopg://...`
- `SECRET_KEY=...`
- `UPLOAD_FOLDER=/path/to/uploads`
- `LOG_FILE=/path/to/logs/app.log`

## HTTPS
- Use `deploy/pilot_nginx.conf` as the base config.
- Enable rate limiting and client body size caps at proxy.

## Upgrade (pilot)
1) Backup DB + uploads
2) `python -m flask --app app:create_app db upgrade`
3) Restart gunicorn
4) Run `scripts/pilot_smoke.sh`
