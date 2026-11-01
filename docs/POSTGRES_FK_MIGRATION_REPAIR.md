# PostgreSQL FK migration repair

## Observed failure and history

GitHub Actions run `41337516551`, commit `61cf021a1d0f2cea0f0a44987b45c420a36785bd`:
the SQLite job passed, while the PostgreSQL migration step failed in
`7b8c9d0e1f2a` on `ALTER TABLE job_report_revisions DROP CONSTRAINT ...`.
The PostgreSQL integration step did not run.

No original Alembic revision creates, renames or drops `job_report_revisions`.
`ab12cd34ef56` creates `error_logs` and template-version fields, not this table.
`fe8d2c9a3b11` only adds `jobs.report_revision`; that scalar counter is separate
from the revision log table. `7b8c9d0e1f2a` assumes the log table and job FK exist.
The ORM `JobReportRevisionLog` model and standalone SQLite legacy upgrader create
the table outside Alembic. Model-created test schemas therefore concealed the
omission; a fresh PostgreSQL upgrade exposed it.

## Correction and deployed compatibility

A new revision alone cannot fix a failure that occurs before it is reached.
The historical revision receives two narrowly limited compatibility corrections:

- Alter the report-table FK only when that table actually exists, in both
  directions. All other FK operations remain mandatory.
- Reflect the costing-sheet/upload FK by its exact source and target columns.
  Revision `4d5e6f7a8b9c` explicitly created
  `fk_costing_sheets_job_costing_upload`; model-created PostgreSQL schemas used
  `costing_sheets_job_costing_upload_id_fkey`. Preserve either existing name;
  fail if no unique named match exists.

Revision identifiers, predecessors and existing branch order remain unchanged.
New revision `d2e3f4a5b6c7` follows `c1d2e3f4a5b6`, creating the omitted table from
a frozen schema snapshot with `job_id -> jobs.id ON DELETE CASCADE`, the user FK
and model indexes. It does not import current models. An existing complete table
and its rows are untouched; an incomplete table causes an explicit failure
rather than a rebuild. Already-upgraded databases receive the new revision
without replaying historical operations.

Automatic downgrade of the new additive revision is deliberately refused: the
table may predate the revision and contain audit history. Any rollback across
this revision requires a separately reviewed plan. No production data or existing
application database was inspected or modified during this repair.

## Audit of all 24 FK operations

The other 23 FK source/target tables and columns exist at predecessor
`6a7b8c9d0e1f`. The costing-sheet/upload constraint-name mismatch is the only
additional naming discrepancy found. Default PostgreSQL names are used below
unless an explicitly named predecessor constraint exists.

| Source FK | Creating revision | Constraint name | Upgrade action |
|---|---|---|---|
| `survey_items.job_id -> jobs.id` | `cb31edff9cc9` | `survey_items_job_id_fkey` | `CASCADE` |
| `part_requirements.job_id -> jobs.id` | `cb31edff9cc9` | `part_requirements_job_id_fkey` | `CASCADE` |
| `part_requirements.survey_item_id -> survey_items.id` | `cb31edff9cc9` | `part_requirements_survey_item_id_fkey` | `SET NULL` |
| `attachments.job_id -> jobs.id` | `cb31edff9cc9` | `attachments_job_id_fkey` | `CASCADE` |
| `template_items.template_id -> templates.id` | `cb31edff9cc9` | `template_items_template_id_fkey` | `CASCADE` |
| `template_groups.template_id -> templates.id` | `cb31edff9cc9` | `template_groups_template_id_fkey` | `CASCADE` |
| `template_item_groups.template_item_id -> template_items.id` | `cb31edff9cc9` | `template_item_groups_template_item_id_fkey` | `CASCADE` |
| `template_item_groups.template_group_id -> template_groups.id` | `cb31edff9cc9` | `template_item_groups_template_group_id_fkey` | `CASCADE` |
| `store_items.template_item_id -> template_items.id` | `cb31edff9cc9` | `store_items_template_item_id_fkey` | `CASCADE` |
| `pick_lists.job_id -> jobs.id` | `cb31edff9cc9` | `pick_lists_job_id_fkey` | `CASCADE` |
| `pick_list_items.pick_list_id -> pick_lists.id` | `cb31edff9cc9` | `pick_list_items_pick_list_id_fkey` | `CASCADE` |
| `audit_logs.job_id -> jobs.id` | `cb31edff9cc9` | `audit_logs_job_id_fkey` | `CASCADE` |
| `job_report_revisions.job_id -> jobs.id` | `omitted; repaired by d2e3f4a5b6c7` | `job_report_revisions_job_id_fkey` | `CASCADE` |
| `job_logs.job_id -> jobs.id` | `7a002b9dbc0e` | `job_logs_job_id_fkey` | `CASCADE` |
| `pre_survey_results.job_id -> jobs.id` | `cb31edff9cc9` | `pre_survey_results_job_id_fkey` | `CASCADE` |
| `epicor_settings.template_id -> templates.id` | `cc_epicor_settings` | `epicor_settings_template_id_fkey` | `SET NULL` |
| `job_costing_uploads.job_id -> jobs.id` | `4d5e6f7a8b9c` | `job_costing_uploads_job_id_fkey` | `CASCADE` |
| `costing_template_profiles.engine_template_id -> templates.id` | `bb_add_costing_models` | `costing_template_profiles_engine_template_id_fkey` | `SET NULL` |
| `costing_template_lines.costing_template_profile_id -> costing_template_profiles.id` | `bb_add_costing_models` | `costing_template_lines_costing_template_profile_id_fkey` | `CASCADE` |
| `costing_sheets.job_id -> jobs.id` | `bb_add_costing_models` | `costing_sheets_job_id_fkey` | `CASCADE` |
| `costing_sheets.job_costing_upload_id -> job_costing_uploads.id` | `4d5e6f7a8b9c` | `fk_costing_sheets_job_costing_upload (or existing legacy name)` | `SET NULL` |
| `costing_sheets.costing_template_profile_id -> costing_template_profiles.id` | `bb_add_costing_models` | `costing_sheets_costing_template_profile_id_fkey` | `SET NULL` |
| `costing_lines.costing_sheet_id -> costing_sheets.id` | `bb_add_costing_models` | `costing_lines_costing_sheet_id_fkey` | `CASCADE` |
| `costing_lines.part_requirement_id -> part_requirements.id` | `bb_add_costing_models` | `costing_lines_part_requirement_id_fkey` | `SET NULL` |

## Regression evidence and limits

`tests/test_fk_cascade_migration.py` migrates a new, guarded SQLite database to
the actual predecessor revision. It inspects that schema and compiles the
PostgreSQL branch with Alembic's offline PostgreSQL dialect, checking every drop
against the predecessor FK names and every replacement against an independent
24-FK policy contract. Upgrade and downgrade are checked with the report table
both absent and present. Missing/ambiguous costing FKs must fail explicitly.

Additional disposable SQLite tests verify the forward table schema, indexes,
actual cascading delete of a test-owned job, repeat application without changing
existing rows/schema, refusal of an unsafe downgrade, refusal to rebuild an
incomplete table, and full fresh migration to the new head.

These are SQLite execution and offline PostgreSQL compilation results, not live
PostgreSQL migration results. The dedicated PostgreSQL CI job, guards, schema
checks and integration assertions remain unchanged and must execute the repair.
The Work sandbox's socket restrictions still prevent local PostgreSQL execution;
no server or container startup was retried. Known later migration risks such as
`ca2e176c395f`'s Boolean `DEFAULT 0` and native enum operations remain outside this
focused repair and may be exposed by the next real PostgreSQL run.
