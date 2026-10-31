#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as exc:
        return exc.returncode, (exc.output or "").strip()


def _check_sqlite_url_abs(db_url: str) -> bool:
    if not db_url.startswith("sqlite:"):
        return True
    if db_url in {"sqlite:///:memory:", "sqlite://"}:
        return False
    return db_url.startswith("sqlite:////")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    env_file = _load_env_file(ROOT / ".env")

    app_env = os.environ.get("APP_ENV") or env_file.get("APP_ENV", "")
    flask_config = os.environ.get("FLASK_CONFIG") or env_file.get("FLASK_CONFIG", "")
    db_url = os.environ.get("DATABASE_URL") or env_file.get("DATABASE_URL", "")
    enable_qb = os.environ.get("ENABLE_QUICKBOOKS") or env_file.get("ENABLE_QUICKBOOKS", "")

    print(f"APP_ENV={app_env or 'UNSET'}")
    print(f"FLASK_CONFIG={flask_config or 'UNSET'}")
    print(f"DATABASE_URL={db_url or 'UNSET'}")
    print(f"ENABLE_QUICKBOOKS={enable_qb or 'UNSET'}")

    if not app_env:
        warnings.append("APP_ENV not explicitly set in environment or .env")
    if not flask_config:
        warnings.append("FLASK_CONFIG not explicitly set in environment or .env")
    if not db_url:
        errors.append("DATABASE_URL is missing")

    strict_mode = (app_env.lower() in {"pilot", "prod", "production"}) or (flask_config.lower() == "production")
    if strict_mode and db_url and not _check_sqlite_url_abs(db_url):
        errors.append("Strict mode requires absolute SQLite URL (sqlite:////abs/path/app.db)")

    if enable_qb not in {"0", "1", "true", "false", "True", "False"}:
        warnings.append("ENABLE_QUICKBOOKS should be explicitly set to 0 or 1")

    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        errors.append(".venv/bin/python not found")
    else:
        rc_py, out_py = _run([str(venv_python), "-V"])
        rc_pipm, out_pipm = _run([str(venv_python), "-m", "pip", "--version"])
        rc_pip, out_pip = _run([str(ROOT / '.venv' / 'bin' / 'pip'), "-V"])

        print(f"VENV_PYTHON={out_py if rc_py == 0 else 'ERROR'}")
        print(f"VENV_PYTHON_M_PIP={out_pipm if rc_pipm == 0 else 'ERROR'}")
        print(f"VENV_PIP_BIN={out_pip if rc_pip == 0 else 'ERROR'}")

        major_minor = None
        m_py = re.search(r"Python\s+(\d+\.\d+)", out_py)
        if m_py:
            major_minor = m_py.group(1)

        if out_pipm and major_minor and f"python {major_minor}" not in out_pipm:
            errors.append("python -m pip is not bound to same Python version")

        if out_pip and major_minor and f"python {major_minor}" not in out_pip:
            warnings.append(".venv/bin/pip points at a different Python version; prefer python -m pip")

        lib_dir = ROOT / ".venv" / "lib"
        py_libs = sorted(p.name for p in lib_dir.glob("python3.*") if p.is_dir())
        print(f"VENV_LIB_DIRS={py_libs}")
        if len(py_libs) > 1:
            warnings.append(f"Multiple Python site-packages trees in .venv: {py_libs}")

    if errors:
        print("FAIL")
        for msg in errors:
            print(f"- {msg}")
        if warnings:
            print("WARNINGS")
            for msg in warnings:
                print(f"- {msg}")
        return 1

    if warnings:
        print("PASS_WITH_WARNINGS")
        for msg in warnings:
            print(f"- {msg}")
        return 0

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
