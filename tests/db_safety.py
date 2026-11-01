"""Connection guards shared by pytest setup and disposable app fixtures."""

import os
from pathlib import Path
import sys

from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url


_allowed_databases = set()
_installed = False
connection_checks = []


def allow_database(path, temporary_root):
    """Designate a new database inside this test's temporary directory."""
    path = Path(path)
    root = Path(temporary_root).resolve()
    if not path.is_absolute() or not path.resolve().is_relative_to(root):
        raise RuntimeError("Test database must be inside its temporary directory")
    if path.exists() or path.is_symlink():
        raise RuntimeError("Refusing to designate an existing database")
    resolved = path.resolve()
    if resolved in _allowed_databases:
        raise RuntimeError("Test database is already designated")
    _allowed_databases.add(resolved)
    return resolved


def forget_database(path):
    _allowed_databases.discard(Path(path).resolve())


def require_disposable_database(target):
    value = os.fspath(target) if isinstance(target, os.PathLike) else target
    if value == ":memory:":
        return
    if isinstance(value, str) and value and not value.startswith("file:"):
        path = Path(value)
        if path.is_absolute() and path.resolve() in _allowed_databases:
            return
    raise RuntimeError("Database safety guard refused a non-designated database")


def install_connection_guards():
    """Install before application imports, including collection-time app setup."""
    global _installed
    if _installed:
        return

    def audit(event_name, args):
        if event_name == "sqlite3.connect":
            require_disposable_database(args[0])
            connection_checks.append(("sqlite", str(args[0])))

    def guard_connection(dialect, connection_record, cargs, cparams):
        if dialect.name == "postgresql":
            from tests.postgres_support import require_postgres_connection
            require_postgres_connection(cargs, cparams)
            return
        if dialect.name != "sqlite":
            raise RuntimeError("Database safety guard permits only disposable SQLite")
        target = cargs[0] if cargs else cparams.get("database")
        require_disposable_database(target)
        connection_checks.append(("engine", str(target)))

    sys.addaudithook(audit)
    event.listen(Engine, "do_connect", guard_connection)
    _installed = True


def assert_engine_database(engine, intended_uri):
    """Check the actual engine, not just Flask's mutable configuration."""
    expected = make_url(intended_uri)
    assert engine.url == expected, (engine.url, expected)
    assert engine.dialect.name == "sqlite"
    require_disposable_database(engine.url.database)
