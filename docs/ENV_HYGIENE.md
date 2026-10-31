# Environment Hygiene

## Goal
Keep runtime deterministic and avoid Python/package drift across environments.

## Quick Check
Run:

```bash
python3 scripts/verify_env_hygiene.py
```

Expected outcome:
- `PASS` or `PASS_WITH_WARNINGS`
- No `FAIL` lines

## Required Conventions
- Always use `python -m pip`, never bare `pip`.
- Keep a single Python minor version per virtual environment.
- Set `DATABASE_URL` explicitly in every environment.
- In pilot/production with SQLite, use absolute URL:
  - `sqlite:////abs/path/to/app.db`
- Set feature flags explicitly:
  - `ENABLE_QUICKBOOKS=0` or `ENABLE_QUICKBOOKS=1`

## Clean venv Rebuild (Recommended when drift is detected)
From repo root:

```bash
mv .venv .venv_old_$(date +%Y%m%d_%H%M%S)
python3.13 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
python3 scripts/verify_env_hygiene.py
```

If successful, remove old venv:

```bash
rm -rf .venv_old_YYYYMMDD_HHMMSS
```

## Notes
- If network access is restricted, package installs may fail; keep the old venv until rebuild can complete.
- After rebuilding, restart app processes to ensure they use the new interpreter and packages.
