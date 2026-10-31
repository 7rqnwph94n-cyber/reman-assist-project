#!/usr/bin/env bash
set -euo pipefail

if [[ "${1-}" == "--help" ]]; then
  echo "Usage: scripts/install_pdf_deps.sh"
  exit 0
fi

if [[ "$(uname)" == "Darwin" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required on macOS. Install from https://brew.sh"
    exit 1
  fi
  brew install pango libffi cairo gobject-introspection
  echo "If WeasyPrint still fails, run:"
  echo "  export DYLD_LIBRARY_PATH=\"/opt/homebrew/lib:/usr/local/lib:\$DYLD_LIBRARY_PATH\""
else
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libffi8
  else
    echo "Unsupported distro. Install Pango/Cairo/GDK/FFI via your package manager."
    exit 1
  fi
fi
