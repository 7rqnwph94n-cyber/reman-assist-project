# Reman Assistant – Testing & Load Harness

This repo includes pytest (unit/RBAC), Playwright (E2E), and Locust (load) harnesses.

## Install test dependencies
```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-test.txt
pip install -r requirements-e2e.txt
pip install -r requirements-load.txt
python -m playwright install
```

## Seed dev/test data
```sh
export FLASK_CONFIG=testing
export APP_ENV=dev
export ALLOW_DANGEROUS_COMMANDS=1
flask seed --reset --templates 2 --jobs 10 --items-per-template 20 --bom-lines-per-job 30
```

## Pytest
```sh
pytest
```

## Playwright E2E
```sh
pytest e2e
```

## Locust (load)
Start the app in another shell (prefer Postgres for real load):
```sh
export FLASK_CONFIG=production
export DATABASE_URL=postgresql://user:pass@localhost:5432/reman
flask run -p 5001
```

Run Locust:
```sh
locust -f load/locustfile.py --host http://127.0.0.1:5001
```

## Notes
- SQLite will not tolerate high concurrency; use Postgres for load tests.
- Seed reset is blocked in production unless explicitly allowed.
- If you are on Python 3.13, `psycopg2-binary` is skipped; use Python 3.11/3.12 for Postgres support.

## Makefile shortcuts
- `make venv` → core deps + pytest
- `make venv-e2e` → Playwright deps (requires `python3.12`)
- `make venv-load` → Locust deps
- `make test` → pytest
- `make e2e` → Playwright E2E
- `make load` → Locust (assumes app on `:5001`)
