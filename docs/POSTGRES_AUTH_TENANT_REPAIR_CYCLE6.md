# Authentication and tenant-isolation repair, cycle 6

Starting checkout: `/Users/richbrotherton/Projects/reman-assist-project`, clean
`dev/review-candidate`, HEAD `ac69bf87945da5247192a048644bf4863a7e1088`.
The original Mac workspace was reconnected before edits. No replacement checkout
was created.

## Root cause and reproduction

[Actions run 41411661584](https://github.com/7rqnwph94n-cyber/reman-assist-project/actions/runs/41411661584)
completed all 43 PostgreSQL migrations, schema verification and repeat upgrade at
`f4a5b6c7d8e9`. Integration reported 8 passed and 3 failed. All failures occurred
at the login helper's 302 assertion, before tenant-denial requests ran.

`job_data` creates and commits both organizations' users with Werkzeug hashes of
the same test password, then logs its client in as organization A's Office user
to create A's job. The cross-organization test posts B's credentials on that
still-authenticated client.

The request hook correctly derives tenant A from the existing session. Because
`User` is a guarded tenant model, `/login`'s `User.query.filter_by(username=...)`
cannot see B's user under A's scope. It follows the invalid-credentials path,
renders `login.html` with HTTP 200 and retains A's authenticated session. Request
teardown correctly clears the tenant context; this is not a leaked context from
an earlier test or a PostgreSQL password/type issue.

Before changing the helper, six guarded SQLite cases reproduced this precisely:
three passed while inspecting the raw failure, and the three positive helper
cases failed with the same 200-versus-302 assertion as CI. For every affected role,
the raw cases verified the committed B user, organization and password hash;
the actual response contained `Invalid username or password`, no lockout warning,
and session `user_id` remained A's Office user. A's own-job page was still readable.
Thus 200 did not mean that B had authenticated.

This is a test lifecycle defect. Cross-tenant account switching without logout
was an invalid setup assumption. Application authentication, query scoping,
password verification, permissions and request hooks are unchanged.

## Correction and review of the 11 integration cases

The test helper now uses the public `/logout` route when already authenticated.
It checks the logout redirect and absent user ID, then posts real credentials to
`/login`. It retains the 302 requirement and verifies the role-specific destination,
the exact session identity, persisted username/role/organization, and login audit.
It never writes an authenticated session or disables a security control.

The fixture now supplies role metadata and a separate B-owned job assigned to B's
Technician. This lets every outsider prove authorized own-job access after login.
All fixture data remains synthetic and uniquely named in PostgreSQL. The session-
scoped PostgreSQL application and function-scoped client remain unchanged; the
bug was reuse inside a single test, not client sharing across tests.

The existing workflow/role cases still use real login requests; the shared helper
also validates Stores' separate landing page. The pre-survey security gate,
idempotency, BOM, audit/revision and transaction rollback assertions remain.
The three uniqueness cases still use their verified PostgreSQL connection and
savepoint/outer transaction rollback. No case is skipped or removed, and CI still
collects 11 mandatory PostgreSQL cases.

## Stronger tenant-isolation contract

The three PostgreSQL isolation cases and separate SQLite regressions share the
same request assertions. All three roles first authenticate as B, inspect the
correct session, query B's own job, and receive 200 for its actual job-detail
page. Foreign Job/Template ORM lookups also remain hidden under B's tenant scope,
even after A's rows have been loaded for the comparison snapshot.

The existing route contracts determine the exact denial codes:

| Foreign A operation | Admin | Office | Technician |
|---|---|---|---|
| GET job detail | 404 | 404 | 404 |
| GET survey | 404 | 404 | 404 |
| POST survey completion | 404 | 404 | 404 |
| GET parts | 404 | 404 | 403 |
| POST parts | 404 | 404 | 403 |
| POST pre-survey | 404 | 403 | 404 |
| POST admin status override | 404 | 403 | 403 |

Roles unsupported by the endpoint are rejected by the role decorator before job
lookup. Supported roles reach tenant-scoped lookup and receive 404. Redirects to
authentication are not accepted as evidence of tenant denial.

After EACH denied request, the tests verify B's session identity and compare both
jobs' full persisted state: job, survey, pre-survey, BOM, audit, report revisions,
measurement audit, attachments and job logs, including IDs and timestamps. The
foreign snapshot must contain the real job and survey rows, preventing an empty
filtered snapshot from producing a false positive.

Finally, Admin and Technician successfully save B's own pre-survey and the notes
are read back from the database. Office remains forbidden and B's state is
unchanged. A's state stays identical in all cases. The additional wrong-password
regression confirms that invalid credentials still produce no authenticated
session and cannot read a protected job.

## Local checks and limits

`tests/test_login_tenant_lifecycle.py` explicitly uses the existing guarded SQLite
factory. It does not replace or alias the PostgreSQL fixture. It imports shared
HTTP assertions without loading/running the PostgreSQL database setup. These are
real Flask/ORM SQLite regression results, not live PostgreSQL results.

Before the reproduction, an actual SQLite memory engine was verified empty and
disposable with connection guards active. Every file fixture is individually
designated and its effective engine URL checked before schema setup by the
existing factory. No existing application database was used.

```sh
PYTHON_DOTENV_DISABLED=1 FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 \
  python -m pytest -ra tests/test_login_tenant_lifecycle.py tests/security_test.py \
  tests/test_tenant_isolation_store_picklist.py tests/test_rbac_matrix.py \
  tests/test_rbac_full.py tests/test_postgres_safety.py
PYTHON_DOTENV_DISABLED=1 FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 \
  python -m pytest -ra
REMAN_RUN_POSTGRES_TESTS=1 PYTHON_DOTENV_DISABLED=1 python -m pytest --collect-only -q postgres_tests
python scripts/migration_check.py --heads-only
```

Live PostgreSQL execution remains **NOT EXECUTED** for this repair. The existing
Work socket restriction was not retried or bypassed. The next real CI run must
exercise these assertions against PostgreSQL. No application/security, migration,
database guard, production configuration, dependency or CI workflow change is
part of this repair. No commit, push, merge or deployment was performed.

Final local results on Python 3.12.12: **108 passed, zero failed/skipped** in the
focused run, and **299 passed, zero failed, 9 skipped** in the full default suite.
The skips remain seven opt-in stress tests and two optional PDF tests. The full
run reported 26 instances of the existing `get_engine()` deprecation warning;
the focused run had no warnings. Database guards recorded 268 permitted
connection checks across 108 designated temporary databases in the full suite.
The focused and full runs exercised the authentication cases in different
collection orders without failures.

PostgreSQL collection passed with all **11 cases and zero connection attempts**.
Alembic still has **43 revisions and one head, `f4a5b6c7d8e9`**. A fresh guarded
SQLite migration reached that exact head. Python syntax and all migration
imports, dependency consistency, unchanged CI YAML structure and whitespace
checks passed. Final review confirmed exactly four changed files, an empty Git
index, unchanged branch/HEAD, and no application/security/guard/migration changes.
