# PostgreSQL uniqueness audit and repair, cycle 5

## Evidence and root cause

Starting checkout: clean `dev/review-candidate`, HEAD
`f8cb93cbd27093a8654be720900ed41b72c74784`.
[Actions run 41341517832](https://github.com/7rqnwph94n-cyber/reman-assist-project/actions/runs/41341517832)
passed the default job. Its PostgreSQL log confirms all 42 migrations completed
and `ALEMBIC_CURRENT` equalled `e3f4a5b6c7d8`. The subsequent schema fingerprint
failed with `Missing unique constraints on templates`; integration never ran.

`Template.__table_args__` requires `(organization_id, name)`. The initial
`cb31edff9cc9` migration instead creates global uniqueness on `templates(name)`.
`9b1c2d3e4f5g` and `a1b2c3d4e5f6` add organization ownership but never replace
that global rule. No other original revision creates the composite rule.
A freshly designated, empty SQLite database migrated through those same 42
revisions reproduces exactly this discrepancy. PostgreSQL SQL generation and
the migration definitions corroborate it; no successful PostgreSQL catalog dump
is available from the failed run.

This is a genuine schema/model mismatch, not a constraint-name or index-reflection
false alarm. Global uniqueness is stricter than the intended per-organization
rule: it also blocks legitimate equal names in different organizations. The old
verifier already considered both reflected unique constraints and unique indexes;
neither supplied the missing composite key.

## Complete uniqueness inventory

All model definitions and all 42 original migration sources were reviewed for
unique constraints, unique indexes, composite keys, naming, creation and removal.
The inventory below contains 18 intended business rules across 15 tables.
Primary keys remain checked separately by the existing verifier.

| Table | Unique columns | Original migration / result |
|---|---|---|
| `engine_types` | `code` | `cb31edff9cc9`; matches |
| `organizations` | `name`; `slug` | `9b1c2d3e4f5g` and `a1b2c3d4e5f6`; matches; slug is a unique index in the fresh path |
| `parts` | `part_no` | `cb31edff9cc9`; matches |
| `users` | `username` | `cb31edff9cc9`; matches; intentionally global |
| `templates` | `organization_id, name` | Missing; obsolete global `name` remains |
| `jobs` | `organization_id, job_number`; `organization_id, job_pack_id` | Both missing; globals from `cb31edff9cc9` / `7a002b9dbc0e` remain |
| `quickbooks_connections` | `organization_id` | `bb8c9d0e1f2a`; constraint `uq_qb_conn_org` is equivalent to the model's unique index |
| `quickbooks_customer_maps` | `organization_id, customer_name_normalized` | `bb8c9d0e1f2a`; matches |
| `template_wizard_states` | `template_id` | `9d0e1f2a3b4c`; matches |
| `attachments` | `job_id, file_hash` | `aa7c9b1d2e3f`; matches; ordinary distinct-NULL semantics |
| `job_costing_uploads` | `job_id, version` | `4d5e6f7a8b9c`; enforced by migrations but omitted from model metadata |
| `pre_survey_results` | `job_id` | `cb31edff9cc9`; matches |
| `store_items` | `template_item_id`; `organization_id, barcode` | `cb31edff9cc9` / `c1d2e3f4a5b6`; matches; old global barcode rule already replaced |
| `template_measurement_specs` | `template_item_id, instance_index` | `9f1a2b3c4d5e`; enforced by migrations but omitted from model metadata |
| `costing_sheets` | `job_id` | `bb_add_costing_models`; matches |

The two metadata omissions are now declared with their existing migration names.
No duplicate database constraint is added for them. This aligns model-created test
schemas with normally migrated installations and makes their absence fail CI.
The fresh migrated schema is checked against every model rule in a regression.

No other missing model uniqueness rule was found. Existing global catalog/user/
organization keys and one-to-one rules are preserved. The historical fallback in
`a1b2c3d4e5f6` can create both a slug constraint and a slug unique index when it
creates an absent organization table; that is an existing alternate-path
redundancy, not a missing safeguard in the fresh chain. It is not changed here.

## Forward migration and data safety

New revision `f4a5b6c7d8e9`, after `e3f4a5b6c7d8`, repairs the three template/job
rules. No historical migration identifier, link or body is edited.

Before any DDL, it checks all intended keys for NULL required values and duplicate
groups. Errors identify the table, columns and duplicate-group count without
printing key values. It refuses invalid/inactive target unique indexes, conflicting
unique-object names, and incoming legacy natural-key FKs that reference a global
key being removed. It never merges, renames, deletes or reassigns records.

Missing composites are created before removing obsolete global rules. Existing
equivalent full unique indexes or constraints are reused, regardless of name or
column order. Standalone legacy unique indexes and named/unnamed constraints are
handled separately; PostgreSQL backing indexes marked `duplicates_constraint`
are not dropped twice. SQLite reflection receives a naming convention solely to
address its unnamed legacy UNIQUE constraints.

On SQLite, a needed parent-table rebuild with FK enforcement enabled is refused
before DDL, without turning enforcement off. Already-correct schemas require no
DDL. PostgreSQL DDL remains in the normal migration transaction; no autocommit or
CASCADE removal is introduced. Automatic downgrade is refused because restoring
global rules could reject legitimate cross-organization values created afterward.

Normally migrated installations already have the two newly declared model rules.
Unknown/stamped legacy schemas missing those rules remain a schema-verification
failure requiring review; this repair does not stamp or reconstruct unknown
application databases. Production data was never accessed.

## Verifier corrections

The original templates failure was legitimate. Separate verifier issues were
found during the audit and corrected without bypassing verification:

- Key order and names do not determine ordinary uniqueness. Reversed composite
  columns and arbitrary constraint/index names are accepted as equivalent.
- INCLUDE columns are not key columns; the pinned SQLAlchemy 2.0.31 PostgreSQL
  reflection code already excludes them from `column_names`. Covering unique
  indexes are accepted using their real key columns.
- Partial and expression indexes cannot stand in for the current ordinary
  full-table model rules. Non-unique indexes, extra key columns and missing rules
  remain failures. Future partial/expression model rules require explicit validation.
- A retained global rule alongside its scoped replacement is rejected: adding
  redundant composites while retaining tenant-blocking globals is not a repair.
- Unexpected `NULLS NOT DISTINCT` on nullable model keys is rejected; for entirely
  non-nullable keys it is semantically equivalent and accepted.
- SQLAlchemy 2.0.31 reflection does not expose index validity/readiness. A read-only
  `pg_catalog.pg_index` check rejects unique indexes that are invalid, not ready,
  or not live. This includes backing indexes and preserves strict gate failure.

Missing-rule diagnostics now include the missing columns. The full schema
fingerprint still includes every public table, constraint, index, default,
sequence, view and enum for repeatability. Target guards, migration receipt
binding, CI service settings and mandatory integration commands are unchanged.

Sources inspected include the installed, pinned SQLAlchemy PostgreSQL dialect
implementation and the official [PostgreSQL pg_index catalog](https://www.postgresql.org/docs/16/catalog-pg-index.html)
and [SQLAlchemy index-reflection documentation](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#postgresql-index-reflection).
Partial predicates are conservatively rejected rather than attempting general
logical proof that an arbitrary predicate is equivalent to a full-table rule.

## Regression coverage and reproduction

`tests/test_unique_schema.py` covers the independent 18-rule inventory and a
negative case for each rule; full schema-fingerprint acceptance/rejection with
PostgreSQL-shaped catalog data; nullable-key semantics; invalid-index refusal;
real predecessor failure; all-model verification after repair; record/audit/child
preservation; same-tenant rejection and cross-tenant acceptance; no redundant
objects on repeated repair or pre-existing equivalent indexes; duplicate/NULL/
name-conflict/natural-FK refusal before DDL; SQLite FK safety; downgrade refusal;
and the six actual PostgreSQL ALTER statements compiled offline.

`postgres_tests/test_uniqueness.py` adds three mandatory PostgreSQL cases. Each
allows the same key in two organizations, checks same-tenant failure SQLSTATE
23505 and the expected constraint, and verifies rows survive savepoint rollback.
Its synthetic rows are contained in a transaction rolled back afterward.
These three cases have **NOT EXECUTED locally**. The dedicated CI suite now has
11 cases, all still explicit opt-in outside CI.

```sh
PYTHON_DOTENV_DISABLED=1 FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 \
  python -m pytest -ra tests/test_unique_schema.py tests/test_postgres_safety.py \
  tests/test_fk_cascade_migration.py tests/test_migration_validation.py \
  tests/test_tenant_isolation_store_picklist.py tests/test_survey_idempotency.py
PYTHON_DOTENV_DISABLED=1 FLASK_CONFIG=testing APP_ENV=test RUN_STRESS_TESTS=0 PILOT_REQUIRE_PDF=0 \
  python -m pytest -ra
python scripts/migration_check.py --heads-only
PYTHON_DOTENV_DISABLED=1 python scripts/ci_migrations.py
python -m pip check
git diff --check
```

Use the existing guarded PostgreSQL commands in README_TESTING.md for a newly
created disposable service; never substitute an existing database. PostgreSQL
sockets remain prohibited in this Work sandbox, and no startup or bypass was
attempted. Local SQLite execution, fake catalog results and offline SQL do not
certify the new PostgreSQL migration, reflection/catalog query, locks, or live
integration behaviour. Those require the next real CI run. Earlier destructive
historical SQL and rollback limitations documented in cycle 3 remain outside
this focused repair.

Final local pytest results on Python 3.12.12: **148 passed, zero failed/skipped**
in the focused run; **288 passed, zero failed, 9 skipped** in the complete default
suite. Skips remain seven stress tests and two optional PDF tests. The focused
run reported 16 and the full run 26 instances of the existing deprecated
`migrations/env.py` `get_engine()` warning. The full run recorded 246 permitted
connection checks against 97 individually designated temporary databases.

Alembic graph checks passed with **43 revisions and one head,
`f4a5b6c7d8e9`**. A fresh, engine-verified guarded SQLite migration reached that
revision. Python syntax and all migration imports, dependency consistency, CI
YAML structure and whitespace checks passed. Collection found all **11 PostgreSQL
cases with zero database connection attempts**; collection is not execution.
The 42 original migration files were verified byte-for-byte unchanged. The index
is empty, and the reviewed diff contains only the eight intended files.
