# Pilot Readiness Gates (P0)

All gates must pass before taking money.

## Gate 1: Auth + role boundaries
- Pass: Admin/Office/Tech/Stores can access only allowed routes.
- Test: `python -m pytest tests/test_pilot_smoke.py -k auth`

## Gate 2: Template import (CSV)
- Pass: CSV import creates template rows + sections.
- Test: `python -m pytest tests/test_pilot_smoke.py -k template_csv`

## Gate 3: Template import (PDF extractor)
- Pass: PDF import works when extractor installed.
- Test: `PILOT_REQUIRE_PDF=1 PILOT_PDF_SAMPLE=/path/to/sample.pdf python -m pytest tests/test_pilot_smoke.py -k template_pdf`

## Gate 4: Job lifecycle transitions
- Pass: Job can be created and moved through allowed statuses without errors.
- Test: `python -m pytest tests/test_pilot_smoke.py -k job_lifecycle`

## Gate 5: Survey idempotency + BOM
- Pass: Survey completion regenerates BOM without duplicates.
- Test: `python -m pytest tests/test_pilot_smoke.py -k bom_idempotency`

## Gate 6: Upload safety
- Pass: blocked file types rejected; path traversal blocked; duplicate attachment hash blocked.
- Test: `python -m pytest tests/test_pilot_smoke.py -k upload_safety`

## Gate 7: PDF export
- Pass: report PDF renders for a large job.
- Test: `PILOT_REQUIRE_PDF=1 python -m pytest tests/test_pilot_smoke.py -k pdf_export`

## Gate 8: Health/ready endpoints
- Pass: `/health` and `/ready` return OK.
- Test: `python -m pytest tests/test_pilot_smoke.py -k health_ready`

## Gate 9: Backup + restore drill
- Pass: Backup and restore to fresh DB + uploads complete.
- Test: `scripts/pilot_gate.sh`

## Gate 10: Proxy rate limiting
- Pass: proxy config installed with rate limits and body size caps.
- Test: verify `deploy/pilot_nginx.conf` installed on server and reloaded.

## One-command gate runner
- `scripts/pilot_smoke.sh`
