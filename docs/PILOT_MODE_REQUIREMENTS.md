# Pilot Mode Requirements (Engineering)

## In-scope workflows (must pass end-to-end)

1) Template import (CSV)
- Route: `POST /admin/templates/<template_id>/wizard?step=1` (action `wizard_import_csv`)
- Code: `templates/routes.py` → `template_wizard()`
- Acceptance: CSV import creates `TemplateItem` rows, updates `TemplateSection` order, and builds canonical parts.
- Verify: Template Wizard Step 1 → import CSV → rows created + Step 1 marked complete.

2) Template import (PDF extractor)
- Route: `POST /admin/templates/<template_id>/wizard?step=1` (action `wizard_import_pdf`)
- Code: `templates/routes.py` → `template_wizard()`
- Acceptance: PDF import runs extractor, loads `parts.csv`, creates `TemplateItem` rows by section/group, and links diagrams.
- Verify: Template Wizard Step 1 → import PDF → sections populated, diagrams visible in Step 3.

3) Job creation + lifecycle transitions
- Routes: `POST /jobs/create`, `POST /jobs/<job_id>/status` (see `jobs/routes.py`)
- Code: `jobs/routes.py`, `services/job_services.py`
- Acceptance: Office creates job, status transitions allowed by role, audit log entries written.
- Verify: Create job, move through statuses, check audit log entry.

4) Survey submission + BOM generation
- Route: `POST /jobs/<job_id>/survey`
- Code: `survey/routes.py`, `services/bom.py`, `services/bom_services.py`
- Acceptance: Survey completion regenerates BOM without duplicates; repeat submit does not duplicate.
- Verify: Submit survey twice; `PartRequirement` count stable.

5) Attachments upload (safe + idempotent)
- Route: `POST /jobs/<job_id>/attachments`
- Code: `jobs/routes.py`, `file_utils.py`
- Acceptance: Allowed types upload successfully; blocked types rejected; duplicate file hash for same job is skipped.
- Verify: Upload a file twice; second is rejected as duplicate.

6) PDF export
- Route: `GET /jobs/<job_id>/report.pdf`
- Code: `services/pdf_renderer.py`, `services/job_pack_export.py`
- Acceptance: Generates PDF without crash; large job works within timeouts.
- Verify: Export a large job report.

7) Health/ready endpoints
- Route: `GET /health`, `GET /ready`
- Code: `app.py`
- Acceptance: Return OK with DB connectivity; errors logged on failure.
- Verify: Curl endpoints.

## Out-of-scope (explicit exclusions)
- Multi-tenant SaaS (org isolation across customers)
- Deep ERP integrations beyond existing endpoints
- Offline mode or mobile sync
- Advanced analytics dashboards
- 24/7 support or SLA uptime guarantees
- Automated onboarding/self-serve signup

## Support boundaries

Allowed manual actions (pilot):
- Config updates (`.env`, proxy config)
- Rerun migrations (`flask db upgrade`)
- Re-run PDF extractor import
- Re-render PDF exports
- Restore from backup

Not allowed:
- Direct DB edits without audit record
- Deleting production data to "fix" a workflow
- Disabling auth/CSRF for convenience
- Sharing a database across customers

## Known risks (Pilot Mode)
- Org isolation not verified everywhere → mitigated by single-tenant deployments
- Survey/BOM idempotency not extensively tested → covered by pilot smoke test
- PDF import depends on external extractor install + profiles
- Rate limiting and upload caps handled at proxy, not in app
- Storage quotas enforced operationally
