import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# Override inherited application database settings before importing app/config.
# Fixture file databases are individually designated before engine creation.
os.environ["FLASK_CONFIG"] = "testing"
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
_test_runtime = TemporaryDirectory(prefix="reman-pytest-")
os.environ["UPLOAD_FOLDER"] = str(Path(_test_runtime.name) / "uploads")
os.environ["LOG_FILE"] = str(Path(_test_runtime.name) / "app.log")
os.environ["REDIS_URL"] = ""

# Ensure project root is on sys.path so imports like `import app` work in tests
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.db_safety import connection_checks, install_connection_guards

install_connection_guards()


def pytest_terminal_summary(terminalreporter):
    files = {target for _, target in connection_checks if target != ":memory:"}
    terminalreporter.write_line(
        f"Database guards: {len(connection_checks)} allowed connection checks, "
        f"{len(files)} designated temporary database(s)."
    )


def pytest_unconfigure(config):
    _test_runtime.cleanup()
