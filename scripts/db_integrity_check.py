#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import db


def _table_exists(inspector, name):
    return name in inspector.get_table_names()


def _count_orphans(conn, child_table, child_fk, parent_table, parent_pk="id"):
    sql = text(
        f"SELECT COUNT(*) FROM {child_table} c "
        f"LEFT JOIN {parent_table} p ON c.{child_fk} = p.{parent_pk} "
        f"WHERE c.{child_fk} IS NOT NULL AND p.{parent_pk} IS NULL"
    )
    return conn.execute(sql).scalar() or 0


def _count_missing(conn, table, column):
    sql = text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
    return conn.execute(sql).scalar() or 0


def main() -> int:
    app = create_app()

    checks = []
    errors = 0

    with app.app_context():
        engine = db.engine
        db_url = engine.url.render_as_string(hide_password=False)
        inspector = inspect(engine)

        with engine.connect() as conn:
            if _table_exists(inspector, "attachments") and _table_exists(inspector, "jobs"):
                checks.append(("attachments.job_id", _count_orphans(conn, "attachments", "job_id", "jobs")))
            if _table_exists(inspector, "part_requirements") and _table_exists(inspector, "jobs"):
                checks.append(("part_requirements.job_id", _count_orphans(conn, "part_requirements", "job_id", "jobs")))
            if _table_exists(inspector, "part_requirements") and _table_exists(inspector, "survey_items"):
                checks.append(("part_requirements.survey_item_id", _count_orphans(conn, "part_requirements", "survey_item_id", "survey_items")))
            if _table_exists(inspector, "survey_items") and _table_exists(inspector, "jobs"):
                checks.append(("survey_items.job_id", _count_orphans(conn, "survey_items", "job_id", "jobs")))
            if _table_exists(inspector, "template_items") and _table_exists(inspector, "templates"):
                checks.append(("template_items.template_id", _count_orphans(conn, "template_items", "template_id", "templates")))
            if _table_exists(inspector, "pick_list_items") and _table_exists(inspector, "pick_lists"):
                checks.append(("pick_list_items.pick_list_id", _count_orphans(conn, "pick_list_items", "pick_list_id", "pick_lists")))

            if _table_exists(inspector, "jobs"):
                checks.append(("jobs.id NULL", _count_missing(conn, "jobs", "id")))
            if _table_exists(inspector, "audit_logs"):
                checks.append(("audit_logs.id NULL", _count_missing(conn, "audit_logs", "id")))

    print(f"Database: {db_url}")
    for label, count in checks:
        status = "OK" if count == 0 else "FAIL"
        print(f"{status} {label}: {count}")
        if count:
            errors += 1

    if errors:
        print(f"Integrity check failed: {errors} issue(s) found.")
        return 1

    print("Integrity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
