from __future__ import annotations

import logging
import os

from flask import jsonify
from sqlalchemy import text


def register_diagnostic_routes(app, *, db) -> None:
    marker = "_reman_diagnostics_registered"
    if app.extensions.get(marker):
        return
    if {"health_check", "ready_check", "version_info"}.issubset(set(app.view_functions.keys())):
        app.extensions[marker] = True
        return

    @app.route("/health")
    def health_check():
        """
        Lightweight health check for monitoring.
        """
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "db": "ok"}), 200
        except Exception:
            logging.exception("Health check failed")
            return jsonify({"status": "error", "db": "error"}), 500

    @app.route("/ready")
    def ready_check():
        """
        Readiness check for dependencies and migrations.
        """
        status = {"status": "ok", "db": "ok", "migrations": "ok", "redis": "skipped"}
        ok = True

        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            logging.exception("Ready check failed: db")
            status["db"] = "error"
            ok = False

        migrations_dir = os.path.join(app.root_path, "migrations")
        alembic_ini = os.path.join(migrations_dir, "alembic.ini")
        if app.config.get("TESTING"):
            status["migrations"] = "skipped"
        elif app.config.get("CHECK_MIGRATIONS_ON_STARTUP", True) and os.path.isdir(migrations_dir) and os.path.exists(alembic_ini):
            try:
                from alembic.config import Config as AlembicConfig
                from alembic.script import ScriptDirectory

                alembic_cfg = AlembicConfig(alembic_ini)
                alembic_cfg.set_main_option("script_location", migrations_dir)
                script = ScriptDirectory.from_config(alembic_cfg)
                heads = set(script.get_heads())
                with db.engine.connect() as conn:
                    rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                current = set(rows)
                if heads and current != heads:
                    status["migrations"] = "out_of_date"
                    ok = False
            except Exception:
                logging.exception("Ready check failed: migrations")
                status["migrations"] = "error"
                ok = False
        else:
            status["migrations"] = "skipped"

        if app.config.get("REQUIRE_REDIS"):
            redis_url = app.config.get("REDIS_URL")
            if not redis_url:
                status["redis"] = "missing"
                ok = False
            else:
                try:
                    import redis  # type: ignore

                    client = redis.Redis.from_url(redis_url)
                    client.ping()
                    status["redis"] = "ok"
                except Exception:
                    logging.exception("Ready check failed: redis")
                    status["redis"] = "error"
                    ok = False

        return jsonify(status), (200 if ok else 503)

    @app.route("/version")
    def version_info():
        """
        Version info for diagnostics.
        """
        payload = {
            "app": "Reman Assistant",
            "version": os.environ.get("APP_VERSION", "unknown"),
            "git_sha": os.environ.get("GIT_SHA", "unknown"),
            "build_time": os.environ.get("BUILD_TIME", "unknown"),
            "flask_env": app.config.get("FLASK_ENV") or os.environ.get("FLASK_ENV"),
            "app_env": app.config.get("APP_ENV") or os.environ.get("APP_ENV"),
        }
        return jsonify(payload), 200

    app.extensions[marker] = True
