# PostgreSQL migration audit, repair cycle 3

## Starting state and observed failure

Reviewed all 41 revisions present at commit
`a21a641ef603f93ee3f3689bdcd2399ea4e4488c`, on `dev/review-candidate`.
The checkout and index were clean before editing.
[Actions run 41339491311](https://github.com/7rqnwph94n-cyber/reman-assist-project/actions/runs/41339491311)
passed its SQLite job. PostgreSQL passed the previously repaired FK migration,
then failed at `462e693b8825` while adding `survey_items.torque_confirmed`:
`BOOLEAN DEFAULT 0` is an integer expression, not a Boolean expression.
The PostgreSQL integration step was skipped after the migration failure.

The log verified an empty test-only database `reman_pg_test_41339491311_1`
at `127.0.0.1:32768`, user `reman_pg_test`, before applying migrations.
This is evidence from the failed CI run, not a successful execution of this repair.

## Corrections and compatibility

Five Boolean columns in three historical revisions had the same defect:

| Revision | Columns | Correction |
|---|---|---|
| `462e693b8825` | `survey_items.torque_confirmed` | `sa.text('0')` to `sa.false()` |
| `6f2c1a0b9d7e` | `template_items.requires_torque`, `requires_build_measure`, `requires_photo` | Same |
| `ca2e176c395f` | `survey_items.is_resolved` | Same |

SQLAlchemy compiles `sa.false()` as `false` on PostgreSQL and `0` on SQLite.
Nullability and default lifetime are unchanged: the torque/template defaults
remain, while the temporary `is_resolved` backfill default is still removed.
The corresponding ORM defaults already use Python `False`; models and application
behaviour do not need alteration. Integer/numeric defaults are left intact.

A forward-only revision cannot fix these failures: PostgreSQL cannot reach that
revision until the older DDL succeeds. These historical changes only correct the
representation of the same false value. Existing revision identifiers, predecessor
links, downgrade operations and stored records are unchanged. Already-upgraded
installations do not replay those revisions and need no Boolean data conversion.

The audit also reproduced three independent schema/model discrepancies:

| Discrepancy | Cause | Forward correction |
|---|---|---|
| `jobstatusenum` lacks `HOLD` | The initial enum predates the current model; no later revision adds the label. | Add `HOLD` using `ADD VALUE IF NOT EXISTS`; retain all existing labels and ordering. |
| `organizations.slug` stays nullable on a fresh chain | `a1b2c3d4e5f6` reuses an inspector that cached the column list before adding `slug`, so its final conditional NOT NULL alteration is missed. | Set NOT NULL after checking existing rows. |
| `job_costing_uploads.uploaded_at` is nullable | `4d5e6f7a8b9c` declares it nullable, while the model requires it. | Set NOT NULL after checking existing rows. |

New additive revision `e3f4a5b6c7d8` follows `d2e3f4a5b6c7`, addressing all three
for both fresh and already-upgraded installations. It checks both required columns
before DDL. Existing null slugs or timestamps cause an explicit failure requiring
manual data review; it never invents historical timestamps, changes ownership,
deletes rows or rebuilds enum types. NOT NULL constraints already present are
retained. SQLite does not use a native job-status enum, so only PostgreSQL receives
the enum DDL.

On SQLite, adding NOT NULL rebuilds the parent tables. If foreign-key enforcement
is enabled and a rebuild is needed, the new revision refuses before DDL, preventing
DROP TABLE from invoking child-row cascades. It never disables foreign-key checks.
Such an installation requires a separately reviewed migration plan. Disposable
SQLite tests exercise both successful record preservation and this refusal.

The new revision deliberately refuses automatic downgrade: removing a PostgreSQL
enum label requires a type rebuild and could invalidate stored HOLD jobs. This
does not change the earlier audit-table repair's existing downgrade refusal.

## Complete revision inventory

The review covered upgrade and downgrade definitions, SQL expressions, native
enums, table dependencies, defaults and constraint names. This table records the
scope of that static review; it does not certify PostgreSQL execution.

| Revision | Review result / remaining concern |
|---|---|
| `cb31edff9cc9` | Tables are created after referenced parents; initial named enums reviewed. Missing HOLD repaired forward. Base downgrade leaves native enum cleanup/reapplication unverified. |
| `7a002b9dbc0e` | Job/release FKs have valid parents. Historical DROP TABLE IF EXISTS operations can destroy pre-existing legacy log/nonconformance rows; not changed. |
| `1a2b3c4d5e6f` | Typed Boolean false; integer quantity defaults valid; temporary defaults removed. |
| `ee4d7c2a9b10` | Integer versions and named attachment FK valid; later nonconformance removal makes arbitrary downgrade paths unsuitable for unreviewed use. |
| `zz_add_supersedes_template_item` | Nullable text addition/removal. |
| `zz_add_bundles_template_item` | Nullable text addition/removal. |
| `aa_add_part_approval` | Typed Boolean false and explicitly named user FK. |
| `bb_add_costing_models` | Native enums created once and reused; Boolean true/false literals valid; child tables dropped before parents. Enum catalog behaviour still needs PostgreSQL. |
| `cc_epicor_settings` | PostgreSQL Boolean true selected explicitly; enum/table creation and teardown reviewed. PostgreSQL branch compiled by regression. |
| `dd_add_procurement_fields` | BACKORDER added without immediate use in data/defaults; named user FK. Downgrade retains the enum label. |
| `ff2b9b1a3c7d` | Merge only; revision links retained. |
| `ab12cd34ef56` | Integer version default valid. Broad exception suppression around template-version backfill is an existing fail-fast/diagnostic concern. |
| `af25d3f4c9ab` | Correct dialect-specific false; temporary default removed. PostgreSQL branch compiled by regression. |
| `fe8d2c9a3b11` | Integer report counter default is valid, not a Boolean. |
| `b1c2d3e4f5a6` | Explicit barcode uniqueness; later tenant-scoped replacement accounted for. |
| `c7d8e9f0a1b2` | Index columns exist in predecessors. |
| `d3e4f5a6b7c8` | PostgreSQL-only audit sequence ownership/default/max-id backfill; live sequence behaviour remains unverified locally. |
| `e1f2a3b4c5d6` | Password hash widening is safe; downgrade to varchar(128) requires review of stored hash lengths. |
| `f2a3b4c5d6e7` | Existing-index inspection; downgrade can remove indexes created by earlier revisions. |
| `9c2d1e7f4a6b` | Merge only; revision links retained. |
| `2b7a9c1e5d10` | Duplicate BACKORDER addition uses IF NOT EXISTS; no immediate use. Downgrade intentionally retains label. |
| `3c4d5e6f7a8b` | Index columns exist in predecessors. |
| `4d5e6f7a8b9c` | Named upload FK matches previous-cycle reflection repair; nullable timestamp repaired forward. |
| `5e6f7a8b9c0d` | Historical removal of nonconformances drops table before native types. Removed records are not restored on downgrade; not changed. |
| `6a7b8c9d0e1f` | Job-pack backfill precedes NOT NULL/check constraints. Existing duplicate/invalid identifiers require review rather than automatic repair. |
| `7b8c9d0e1f2a` | Previous-cycle 24-FK audit/tests preserved; CI passed this revision in run 3. No further missing source-table/name defect found. |
| `8c9d0e1f2a3b` | Illustration parents precede child/link tables; downgrade order reversed. |
| `9d0e1f2a3b4c` | String status and integer step defaults valid; template parent exists. |
| `9e0f1a2b3c4d` | Canonical part/occurrence parent order and integer quantity default valid. |
| `9f1a2b3c4d5e` | Measurement-spec FK/uniqueness names and dependencies valid. |
| `462e693b8825` | Confirmed failing Boolean default corrected; audit-log FKs/indexes reviewed; downgrade tested on disposable data. |
| `6f2c1a0b9d7e` | Three additional Boolean defaults corrected; downgrade tested on disposable data. |
| `7c1d2e3f4a5b` | Application log parent FKs and string level default valid. |
| `8a1b2c3d4e5f` | Job/measurement-audit index columns exist. |
| `9b1c2d3e4f5g` | Organization parents precede ownership FKs; backfill uses bound SQL values. Legacy data migration assumes a single original organization. |
| `a1b2c3d4e5f6` | Slug nullability omission repaired forward. Downgrade also removes ownership columns introduced by its predecessor; full-chain rollback is not certified. |
| `ca2e176c395f` | Boolean default corrected. MACHINING addition has no same-transaction DML/default use; downgrade retains enum label. |
| `aa7c9b1d2e3f` | PostgreSQL deduplication SQL and unique constraint names reviewed. Historical deduplication deletes matching rows; SQLite downgrade has an unsupported direct constraint drop. Not changed. |
| `bb8c9d0e1f2a` | Correct PostgreSQL true defaults and enum creation/reuse; SQLite string fallback preserved. PostgreSQL branch compiled by regression. |
| `c1d2e3f4a5b6` | Ownership backfills and named constraints reviewed; orphan checks retained. Broad exception suppression around uniqueness/downgrade is an existing concern; cross-tenant duplicate barcodes also make restoring global uniqueness unsafe without review. |
| `d2e3f4a5b6c7` | Previous-cycle report-table repair and audit-data downgrade refusal preserved. |

New revision `e3f4a5b6c7d8` adds no table or column dependency: all referenced
objects are present at its predecessor. Its PostgreSQL SQL is compiled offline;
its data-preserving/refusal paths are executed on guarded disposable SQLite.

## Enum transactions and outstanding safety work

PostgreSQL 16 permits ADD VALUE inside a transaction, but a newly added label
cannot be used until commit. The existing BACKORDER/MACHINING operations and new
HOLD operation do not use those labels in migration DML or defaults. No autocommit
block is needed for these changes; unnecessary early commits would reduce migration
atomicity. Schema reflection and integration use occur after upgrade returns.
See the [PostgreSQL 16 ALTER TYPE documentation](https://www.postgresql.org/docs/16/sql-altertype.html).

Remaining risks above are not hidden by skips, exception handlers or weakened gate
assertions in this repair. Historical destructive SQL, legacy adoption assumptions,
suppressed errors and full-chain downgrade/re-upgrade need separate focused work
with synthetic populated databases and explicit rollback policy. No existing
application database or production credentials were used to assess them.

## Reproduction and evidence

Use the existing Python 3.12 setup and disposable guards in README_TESTING.md:

```sh
PYTHON_DOTENV_DISABLED=1 FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 \
  python -m pytest -ra tests/test_postgres_migration_compatibility.py tests/test_fk_cascade_migration.py \
  tests/test_migration_validation.py tests/test_postgres_safety.py tests/test_survey_idempotency.py
PYTHON_DOTENV_DISABLED=1 FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 \
  python -m pytest -ra
python scripts/migration_check.py --heads-only
PYTHON_DOTENV_DISABLED=1 python scripts/ci_migrations.py
python -m pip check
git diff --check
```

The additional tests scan every revision's Boolean column defaults (both directions),
reject numeric/unaudited defaults, compile six actual PostgreSQL upgrade branches,
check the migration enum-label inventory against current models, exercise false
backfills/true values/default lifetime/targeted downgrades, and validate the new
forward repair's preservation and refusal cases. The earlier report-table test now
checks that its repair is an ancestor of the current head rather than freezing the
head forever. Its table-presence and effective database-revision assertions remain.

PostgreSQL migration execution, catalog reflection and integration tests for this
change are **NOT EXECUTED locally**. The Work sandbox prohibits PostgreSQL sockets;
no server startup or bypass was attempted. Offline compilation is not server-side
type checking. The mandatory PostgreSQL 16 CI gate, service, credentials, guards,
receipt binding, schema assertions and integration cases remain unchanged.

Local validation on Python 3.12.12: the focused command passed **150 tests** with
zero failures/skips; the complete default suite passed **231 tests**, with zero
failures and **9 intentional skips** (seven stress tests, two optional PDF tests).
Both runs reported 20 warnings from the existing deprecated `get_engine()` call
in `migrations/env.py`. The full suite recorded 222 allowed connection checks
against 85 designated temporary databases. These counts include the existing
PostgreSQL guard and survey-idempotency regressions.

Migration graph validation passed with **42 revisions and one head,
`e3f4a5b6c7d8`**. `scripts/ci_migrations.py` verified a newly designated empty
SQLite engine and migrated it to that exact revision. All migration imports and
Python syntax, CI YAML structure, `pip check`, and whitespace checks passed.
The new Boolean checker also rejected all five original defects when run on the
41 original revision sources from Git. All original revision identifiers and
links were verified unchanged; the index remains empty.
