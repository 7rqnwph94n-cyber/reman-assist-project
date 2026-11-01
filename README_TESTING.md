# Reman Assist v1.0 — Independent Review Candidate: testing

## Supported environment

Use Python **3.12** for this review candidate (verified locally with 3.12.12).
CI uses Python 3.12 on a clean Ubuntu runner. Python 3.13 is outside this baseline.
Run commands from the repository root; no personal Mac paths are required.

```sh
python3.12 -m venv .venv312
source .venv312/bin/activate
python -m pip install -r requirements.txt -r requirements-test.txt
python -m pip check
```

The default gate requires no Playwright browser or load-test dependencies.
Dependencies retain their existing constraints; this is not a complete transitive
lockfile. WeasyPrint uses platform native libraries when available. Existing PDF
smoke tests retain their configured fallback; the optional pilot PDF tests are
separate. Mac native-library hints run only when `sys.platform == "darwin"`.

## Default tests and database safety

```sh
FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 python -m pytest -ra
```

`pytest.ini` selects the complete `tests/` suite, excluding `e2e/`. The expected
review baseline is **87 passed, 9 skipped**. The nine intentional skips are seven
stress/integration tests gated by `RUN_STRESS_TESTS=1` and two pilot PDF tests
gated by `PILOT_REQUIRE_PDF=1`; PDF import additionally requires a sample file.
These opt-ins remain disabled in CI. Other PDF/report smoke tests still run.

Root `conftest.py` overrides inherited database settings before importing the app.
SQLAlchemy and Python SQLite connection guards allow only memory databases or
exact file paths designated inside the current test's `tmp_path`. Existing
files cannot be designated. There is no directory-wide database allowlist.

Use `test_app_factory(database_uri=...)` for database tests. It supplies a fresh
Flask app and applies configuration before SQLAlchemy initialisation. Before
creating tables, it asserts that the effective engine URL equals the intended
disposable URL. Teardown checks the engine again, removes sessions, drops only
the verified test schema and disposes engines. The default URI targets
`tmp_path / "test.db"`; pass `sqlite:///:memory:` to request a fresh memory engine.
Pass other configuration overrides as keyword arguments. Do not reset Flask's
private flags or change the database URI after creating an app.

Focused factory, safety, security and survey regressions:

```sh
python -m pytest -ra tests/test_fixture_lifecycle.py tests/test_survey_idempotency.py tests/test_migration_validation.py tests/test_seed_guard.py tests/test_upload_smoke.py tests/test_presurvey_and_nc.py tests/security_test.py
```

Do not seed or reset an application database to run the default suite.

## Migration checks and CI

```sh
python scripts/migration_check.py --heads-only
python scripts/ci_migrations.py
```

The first command validates the migration graph and requires exactly one head.
It imports no application and opens no database. The second creates a new file
inside `TemporaryDirectory`, designates that exact file, and installs the same
SQLAlchemy and SQLite guards before importing the app. It verifies the effective
engine URL, `PRAGMA database_list` and an empty database before running the full
Alembic upgrade. It then compares actual `alembic_version` revisions with the
expected graph head. No `db.create_all()`, stamping or existing database is used
as a substitute for applying migrations. The temporary database is disposed and
removed afterwards. Any migration or revision mismatch fails the command.

Without `--heads-only`, `scripts/migration_check.py` retains its read-only runtime
revision check for support scripts. CI does not use that runtime database path.

`.github/workflows/ci.yml` runs checkout, Python 3.12 dependency installation,
`python -m pip check`, the database-free graph check, the guarded fresh-database
upgrade/alignment check, and the complete default pytest suite. Genuine errors
fail the job; no step masks a failure. No application database is migrated.
SQLite paths come from Python temporary directories, on both macOS and Ubuntu.
This gate validates SQLite migrations; it does not validate PostgreSQL migrations.

YAML parsing and local commands can be verified locally. A local pass does not
mean GitHub Actions or a clean Ubuntu dependency installation has run successfully.

## Separate opt-in harnesses

E2E requires `requirements-e2e.txt` and installed Playwright browsers. Its server
fixtures create separate disposable databases before starting the app. It is
not part of the default gate:

```sh
python -m pip install -r requirements-e2e.txt
python -m playwright install
python -m pytest e2e
```

Stress, pilot PDF and Locust checks require a separately configured disposable
environment, appropriate data and any additional dependencies. Never point them
at user or production databases. Load dependencies are in `requirements-load.txt`.
The Makefile's existing `.venv` shortcuts remain available, but use the explicit
Python 3.12 setup above for reproducibility.
