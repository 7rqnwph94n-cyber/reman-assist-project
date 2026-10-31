#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

ENGINE="${1:-auto}" # auto|weasyprint|playwright
VERIFY_ONLY="${VERIFY_ONLY:-0}"
VENV_PYTHON="${VENV_PYTHON:-./.venv/bin/python}"

usage() {
  cat <<'EOF'
Usage:
  scripts/install_pdf_renderer.sh [auto|weasyprint|playwright]

Options via env:
  VERIFY_ONLY=1      Skip installs; only run readiness and export smoke checks.
  VENV_PYTHON=...    Python interpreter to use (default: ./.venv/bin/python).

Examples:
  scripts/install_pdf_renderer.sh auto
  scripts/install_pdf_renderer.sh weasyprint
  VERIFY_ONLY=1 scripts/install_pdf_renderer.sh auto
EOF
}

if [[ "${ENGINE}" == "-h" || "${ENGINE}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "FAIL: Python interpreter not found/executable: $VENV_PYTHON" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "FAIL: this installer currently targets macOS only." >&2
  echo "Use scripts/install_pdf_deps.sh plus pip installs on your OS." >&2
  exit 1
fi

ensure_brew_pkg() {
  local pkg="$1"
  if brew list --versions "$pkg" >/dev/null 2>&1; then
    echo "OK: brew package present: $pkg"
  else
    echo "Installing brew package: $pkg"
    brew install "$pkg"
  fi
}

install_weasyprint_path() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "FAIL: Homebrew is required for WeasyPrint system libs." >&2
    exit 1
  fi
  ensure_brew_pkg cairo
  ensure_brew_pkg pango
  ensure_brew_pkg gdk-pixbuf
  ensure_brew_pkg libffi

  "$VENV_PYTHON" -m pip install "weasyprint==67.0"

  # Runtime hint for macOS dynamic libs.
  export DYLD_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib:${DYLD_LIBRARY_PATH:-}"
}

install_playwright_path() {
  "$VENV_PYTHON" -m pip install "playwright>=1.47,<2"
  "$VENV_PYTHON" -m playwright install chromium
}

run_readiness() {
  export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp}"
  export FONTCONFIG_PATH="${FONTCONFIG_PATH:-/opt/homebrew/etc/fonts}"
  "$VENV_PYTHON" - <<'PY'
from services.pdf_renderer import get_pdf_renderer_status
print(get_pdf_renderer_status())
PY
}

run_smoke() {
  export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp}"
  export FONTCONFIG_PATH="${FONTCONFIG_PATH:-/opt/homebrew/etc/fonts}"
  "$VENV_PYTHON" scripts/export_smoke.py --output-dir /tmp/reman_export_smoke
}

if [[ "$VERIFY_ONLY" != "1" ]]; then
  case "$ENGINE" in
    weasyprint)
      install_weasyprint_path
      ;;
    playwright)
      install_playwright_path
      ;;
    auto)
      echo "Attempting WeasyPrint path first..."
      if ! install_weasyprint_path; then
        echo "WeasyPrint path failed; trying Playwright path..."
        install_playwright_path
      fi
      ;;
    *)
      echo "FAIL: invalid engine '$ENGINE' (use auto|weasyprint|playwright)" >&2
      exit 1
      ;;
  esac
fi

echo "Renderer readiness:"
run_readiness

echo "Running export smoke..."
run_smoke

echo "PASS: PDF renderer install/verify complete."
