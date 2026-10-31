from __future__ import annotations

import os
from flask import Flask
from sqlalchemy import text


def is_strict_runtime_mode(app: Flask) -> bool:
    cfg_name = (os.environ.get("FLASK_CONFIG") or "").lower()
    app_env = (app.config.get("APP_ENV") or os.environ.get("APP_ENV") or "").lower()
    return cfg_name == "production" or app_env in {"pilot", "prod", "production"}


def resolve_sqlite_db_path(db_url: str, base_dir: str) -> str | None:
    if not db_url.startswith("sqlite:"):
        return None
    if db_url in {"sqlite:///:memory:", "sqlite://"}:
        return None
    if db_url.startswith("sqlite:////"):
        return os.path.abspath("/" + db_url.replace("sqlite:////", "", 1))
    if db_url.startswith("sqlite:///"):
        rel = db_url.replace("sqlite:///", "", 1)
        return os.path.abspath(os.path.join(base_dir, rel))
    return None


def validate_database_config(app: Flask, base_dir: str) -> None:
    db_url = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    strict_mode = is_strict_runtime_mode(app)
    explicit_db_url = os.environ.get("DATABASE_URL")
    if strict_mode and not explicit_db_url:
        raise RuntimeError(
            "DATABASE_URL is required in pilot/production. "
            "Refusing to start with fallback database settings."
        )
    if strict_mode and db_url.startswith("sqlite:") and not db_url.startswith("sqlite:////"):
        raise RuntimeError(
            "SQLite DATABASE_URL must be absolute in pilot/production "
            "(sqlite:////abs/path/to/app.db)."
        )
    sqlite_path = resolve_sqlite_db_path(db_url, base_dir)
    if sqlite_path:
        app.config["CONFIG_SQLITE_DB_PATH"] = sqlite_path
    app.config["STRICT_RUNTIME_MODE"] = strict_mode


def get_migration_revisions(app: Flask, db) -> tuple[list[str], list[str], str | None]:
    migrations_dir = os.path.join(app.root_path, "migrations")
    alembic_ini = os.path.join(migrations_dir, "alembic.ini")
    if not os.path.isdir(migrations_dir) or not os.path.exists(alembic_ini):
        return [], [], "migrations config missing"
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory
    except Exception as exc:
        return [], [], f"alembic unavailable: {exc}"

    alembic_cfg = AlembicConfig(alembic_ini)
    alembic_cfg.set_main_option("script_location", migrations_dir)
    script = ScriptDirectory.from_config(alembic_cfg)
    heads = sorted(set(script.get_heads()))
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    except Exception as exc:
        return [], heads, f"current revision unavailable: {exc}"
    current = sorted(set(rows))
    return current, heads, None


def record_runtime_db_details(app: Flask, db) -> None:
    runtime_db_url = db.engine.url.render_as_string(hide_password=False)
    app.config["RUNTIME_DATABASE_URL"] = runtime_db_url
    runtime_sqlite_path = (
        os.path.abspath(db.engine.url.database)
        if db.engine.url.drivername.startswith("sqlite") and db.engine.url.database
        else None
    )
    if runtime_sqlite_path:
        app.config["RUNTIME_SQLITE_DB_PATH"] = runtime_sqlite_path


def log_runtime_db_details(app: Flask, db) -> None:
    db_url = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    runtime_db_url = str(app.config.get("RUNTIME_DATABASE_URL") or "")
    app.logger.info("Startup config DB URI: %s", db_url)
    app.logger.info("Startup runtime DB URI: %s", runtime_db_url)
    if db_url != runtime_db_url:
        app.logger.warning(
            "Config DB URI and runtime DB URI differ. Use absolute DATABASE_URL to avoid split-brain."
        )
    cfg_sqlite_path = app.config.get("CONFIG_SQLITE_DB_PATH")
    runtime_sqlite_path = app.config.get("RUNTIME_SQLITE_DB_PATH")
    if cfg_sqlite_path:
        app.logger.info("Startup config SQLite path: %s", cfg_sqlite_path)
    if runtime_sqlite_path:
        app.logger.info("Startup runtime SQLite path: %s", runtime_sqlite_path)
