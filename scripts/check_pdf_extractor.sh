#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import os
import sys

try:
    from pdf_parts_extractor.extract import run_extract
    from pdf_parts_extractor.profiles import list_profiles
except Exception as exc:
    print(f"ERROR: pdf_parts_extractor not importable: {exc}")
    sys.exit(1)

profiles = list_profiles()
if not profiles:
    print("ERROR: No profiles found. Set PDF_EXTRACTOR_PROFILES_DIR.")
    sys.exit(1)

print("OK: pdf_parts_extractor importable")
print(f"Profiles: {', '.join([os.path.basename(p) for p in profiles])}")
print(f"PDF_EXTRACTOR_PROFILES_DIR={os.environ.get('PDF_EXTRACTOR_PROFILES_DIR')}")
PY
