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
review baseline is **231 passed, 9 skipped**, including 69 socket-free PostgreSQL
configuration/guard unit cases. The nine intentional skips are seven
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
The existing `test` job validates SQLite migrations. The separate PostgreSQL job
below validates PostgreSQL migrations and application integration.

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


## Dedicated PostgreSQL 16 gate

The `postgres` GitHub Actions job uses a new `postgres:16` service on each run,
with a database named `reman_pg_test_<run_id>_<attempt>` and a dynamically mapped
loopback port. Service health checks use `pg_isready`; the migration runner also
performs a bounded connection-readiness check. Python 3.12 and the existing
`psycopg2-binary==2.9.9` requirement are used; no dependency upgrades are needed.

`REMAN_RUN_POSTGRES_TESTS=1` is mandatory. `postgres_tests/` is outside the default
`pytest.ini` test paths, and explicitly selecting it without opt-in fails rather
than skipping or using SQLite. The dedicated CI job always opts in and runs:

```sh
python -m pip install -r requirements.txt -r requirements-test.txt
python -m pip check
python scripts/migration_check.py --heads-only
python scripts/ci_postgres.py --receipt "$REMAN_PG_TEST_RECEIPT"
python -m pytest -ra postgres_tests
```

The PostgreSQL guard permits only `127.0.0.1`, the exact designated mapped port,
the database derived from the run ID, and the fixed test-only user/password
shown below. Unknown DSN options, alternate hosts, database names, credentials
and inherited libpq `PG*` environment settings are rejected before a driver
connection. Both SQLAlchemy and raw psycopg2 connections are guarded. Existing
SQLite file/memory guards are unchanged and remain active. Application `.env`
loading is disabled for the PostgreSQL gate; `DATABASE_URL` is never accepted as
an input target.

The migration runner verifies PostgreSQL major version 16, database name, owner,
login/session role, application name, cluster identifier and database OID. It requires an
empty public schema and no other user schemas, relations, types or routines
before migrating. It applies the complete Alembic chain without stamping or
`create_all()`, then checks revision, model tables/columns, primary keys, nullability,
enum labels, foreign keys and unique constraints. The repeatability fingerprint
includes all public tables, column defaults, indexes, constraints, sequences,
views, materialized views and enum definitions, including non-model objects.
A repeated upgrade must leave that fingerprint and revision unchanged. Any
failure fails the job.

Only after those checks does it exclusively create a new migration receipt.
The receipt has a versioned format and includes the database OID, so recreating
the same database name in the same cluster invalidates an earlier receipt.
Integration fixtures require that receipt and recheck target, cluster/database
instance, revision and schema fingerprint. Tests commit real PostgreSQL transactions, use unique
rows per case and dispose sessions/engines afterwards. They never drop, truncate,
reset or delete a database. Cases cover organisations and all user roles, HTTP
job creation, the persisted pre-survey gate, survey completion and repeat
submission, BOM quantities, audits/revisions, workflow completion guards,
cross-organisation access and transaction rollback. The isolated service is
removed by GitHub Actions when the job ends.

### Explicit local execution outside a socket-restricted Work session

Do not run these commands inside a Work session that prohibits sockets. They
require a functioning Docker daemon and permission to use local sockets. Start
a **new** container; do not reuse an existing application database or source
credentials from application environment files. No containers or databases are
started automatically by the test runner.

```sh
export REMAN_RUN_POSTGRES_TESTS=1
export REMAN_PG_TEST_ID="local_$(python -c 'import uuid; print(uuid.uuid4().hex[:12])')"
export REMAN_PG_TEST_HOST=127.0.0.1
export REMAN_PG_TEST_DATABASE="reman_pg_test_$REMAN_PG_TEST_ID"
export REMAN_PG_TEST_USER=reman_pg_test
export REMAN_PG_TEST_PASSWORD=reman-postgres-ci-only
export REMAN_PG_TEST_RECEIPT="$(mktemp -d /tmp/reman-pg-receipt-XXXXXX)/receipt.json"

docker run --rm -d --name "$REMAN_PG_TEST_DATABASE" \
  -e POSTGRES_USER="$REMAN_PG_TEST_USER" \
  -e POSTGRES_PASSWORD="$REMAN_PG_TEST_PASSWORD" \
  -e POSTGRES_DB="$REMAN_PG_TEST_DATABASE" \
  -p 127.0.0.1::5432 postgres:16
export REMAN_PG_TEST_PORT="$(docker inspect --format='{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}' "$REMAN_PG_TEST_DATABASE")"

python scripts/ci_postgres.py --receipt "$REMAN_PG_TEST_RECEIPT"
python -m pytest -ra postgres_tests
```

All inherited libpq `PG*` variables must be absent; the guard refuses them rather
than silently ignoring potentially redirecting options. The published credentials
are exclusively for this disposable service. Its internal PostgreSQL port is 5432;
the approved host port is the one reported by Docker. The receipt path must be new.
The migration runner deliberately refuses a second full invocation against the
now-populated database; its internal repeated `upgrade head` verifies repeatability.
Use another newly created service/database/receipt for another full gate run.

**Execution status:** PostgreSQL migrations, schema checks, repeated upgrade and
integration tests have **NOT EXECUTED** in the socket-restricted Work environment.
They remain unverified until this workflow completes them successfully. Default-suite tests in
`tests/test_postgres_safety.py` validate rejection and configuration using pure
inputs and fake drivers; those results are not PostgreSQL integration results.
Neither local SQLite success nor YAML parsing is evidence of a PostgreSQL pass.


PostgreSQL-specific migration behaviour still requires a live run. Native enum
creation/alteration and PostgreSQL constraint reflection cannot be established
from the SQLite suite. Newly added enum values must not be used until the
transaction adding them commits. The gate must fail on remaining discrepancies.


The first real PostgreSQL failure and its focused repair are documented in
[the FK migration audit](docs/POSTGRES_FK_MIGRATION_REPAIR.md). Revision
`d2e3f4a5b6c7` repairs that omission. Thirteen migration regressions cover the missing
report table, all FK operations and existing-schema/audit-data compatibility.
Automatic downgrade of this additive audit-table repair is refused to protect
existing revision history. Live PostgreSQL verification of the repair is pending.

Cycle 3's [complete 41-revision audit](docs/POSTGRES_MIGRATION_AUDIT_CYCLE3.md)
corrects five integer Boolean defaults in three historical migrations. The new
head is `e3f4a5b6c7d8` (42 revisions): an additive repair supplies PostgreSQL's
missing HOLD job-status label and enforces the model's required organization slug
and upload timestamp. Existing nulls stop the upgrade for manual data review;
automatic downgrade and unsafe SQLite parent rebuilds with foreign keys enabled
are refused. No records are fabricated or deleted. Sixty-two new socket-free
regressions cover defaults across every revision, PostgreSQL SQL compilation,
enum labels, backfills, targeted downgrades and forward-repair safety. Use the
focused commands in the audit document or the complete default suite above.
The PostgreSQL CI gate and disposable database guards remain unchanged. Live
PostgreSQL execution of these corrections is still pending.
