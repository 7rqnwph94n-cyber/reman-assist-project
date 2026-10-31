# PDF Import (Extractor) — Pilot Ops

## Install
```
python3 -m pip install -e "/path/to/pdf-parts-extractor"
```

## Profiles
- Set profiles dir: `PDF_EXTRACTOR_PROFILES_DIR=/path/to/pdf-parts-extractor/profiles`
- Profiles are discovered by `pdf_parts_extractor.profiles.list_profiles()`

## Health check
```
scripts/check_pdf_extractor.sh
```

## Runtime behavior
- Template Wizard → Step 1 → PDF Import
- Extractor writes `parts.csv` and diagram images to a temp directory
- Import uses `group_id` or `section` columns for sections
- Diagrams are copied into `UPLOAD_FOLDER/illustrations/<template_id>`

## Failure message
If missing, UI shows: "PDF extractor not available. Run scripts/check_pdf_extractor.sh and fix any errors."
