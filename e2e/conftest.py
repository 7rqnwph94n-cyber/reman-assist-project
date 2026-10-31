import os
import sys
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright


def _wait_for_health(url: str, timeout: int = 30) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urlopen(url, timeout=2) as resp:  # nosec - local test server
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Server did not become healthy at {url}")


def _start_server(tmp_root, seed_args, port):
    db_path = tmp_root / "e2e.db"
    uploads = tmp_root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[1]
    app_python = os.environ.get("APP_PYTHON") or str(repo_root / ".venv" / "bin" / "python")
    if not os.path.exists(app_python):
        app_python = sys.executable

    env = os.environ.copy()
    env.update(
        {
            "FLASK_APP": "app:create_app",
            "FLASK_CONFIG": "testing",
            "APP_ENV": "dev",
            "ALLOW_DANGEROUS_COMMANDS": "1",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "UPLOAD_FOLDER": str(uploads),
            "WTF_CSRF_ENABLED": "false",
            "ENFORCE_CSRF": "false",
            "ENABLE_TEST_SELECTORS": "1",
            "SESSION_COOKIE_SECURE": "false",
        }
    )

    subprocess.run(
        [app_python, "-m", "flask", "seed", "--reset"] + seed_args,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    proc = subprocess.Popen(
        [app_python, "-m", "flask", "run", "-p", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    _wait_for_health(f"{base}/health")
    return proc, base


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    tmp_root = tmp_path_factory.mktemp("e2e")
    proc, base = _start_server(
        tmp_root,
        seed_args=["--templates", "1", "--jobs", "2", "--items-per-template", "6", "--bom-lines-per-job", "6"],
        port=5006,
    )
    yield base
    proc.terminate()


@pytest.fixture
def server_factory(tmp_path_factory):
    procs = []

    def _make(seed_args, port):
        tmp_root = tmp_path_factory.mktemp(f"e2e_{port}")
        proc, base = _start_server(tmp_root, seed_args=seed_args, port=port)
        procs.append(proc)
        return base

    yield _make
    for proc in procs:
        proc.terminate()


@pytest.fixture
def page():
    with sync_playwright() as p:
        headless = os.environ.get("PW_HEADLESS", "false").lower() in {"1", "true", "yes", "on"}
        browser_name = os.environ.get("PW_BROWSER", "chromium").lower()
        browser_type = {"chromium": p.chromium, "firefox": p.firefox, "webkit": p.webkit}.get(
            browser_name, p.chromium
        )
        launch_args = ["--disable-crash-reporter", "--disable-breakpad", "--no-sandbox"]
        try:
            browser = browser_type.launch(headless=headless, args=launch_args)
        except Exception:
            # Fallback to a more reliable engine on macOS if Chromium crashes.
            fallback = p.webkit if browser_type is p.chromium else p.chromium
            browser = fallback.launch(headless=headless)
        page = browser.new_page()
        yield page
        browser.close()
