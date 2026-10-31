#!/usr/bin/env python3
"""
Non-destructive schema upgrades for legacy SQLite DBs.
Adds missing columns/tables required by the current app.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import os
import subprocess
import sys


def add_column_if_missing(cur: sqlite3.Cursor, table: str, column: str, coldef: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    if column in cols:
        return False
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
    return True


def table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def main() -> int:
    parser = argparse.ArgumentParser(description="Upgrade a legacy Reman Assistant SQLite DB.")
    parser.add_argument(
        "--db",
        default="app.db",
        help="Path to SQLite DB file (default: app.db)",
    )
    parser.add_argument(
        "--stamp-head",
        action="store_true",
        help="Stamp Alembic to head after upgrading (avoids duplicate column errors).",
    )
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    changed = []

    # jobs table
    for col, coldef in [
        ("survey_version", "INTEGER DEFAULT 0"),
        ("parts_version", "INTEGER DEFAULT 0"),
        ("template_version", "INTEGER DEFAULT 1"),
        ("report_revision", "INTEGER DEFAULT 0"),
    ]:
        if add_column_if_missing(cur, "jobs", col, coldef):
            changed.append(f"jobs.{col}")

    # templates table
    if add_column_if_missing(cur, "templates", "version", "INTEGER DEFAULT 1"):
        changed.append("templates.version")

    # attachments table
    if add_column_if_missing(cur, "attachments", "original_filename", "VARCHAR(255)"):
        changed.append("attachments.original_filename")
    if add_column_if_missing(cur, "attachments", "uploaded_by_id", "INTEGER"):
        changed.append("attachments.uploaded_by_id")

    # users table
    if add_column_if_missing(cur, "users", "force_password_reset", "BOOLEAN DEFAULT 0"):
        changed.append("users.force_password_reset")

    # part_requirements table
    for col, coldef in [
        ("backorder_reason", "VARCHAR(255)"),
        ("qty_received", "INTEGER DEFAULT 0"),
        ("received_at", "DATETIME"),
        ("received_by_id", "INTEGER"),
    ]:
        if add_column_if_missing(cur, "part_requirements", col, coldef):
            changed.append(f"part_requirements.{col}")

    # store_items table
    if add_column_if_missing(cur, "store_items", "barcode", "VARCHAR(64)"):
        changed.append("store_items.barcode")

    # report revisions table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS job_report_revisions (
            id INTEGER PRIMARY KEY,
            job_id INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            reason VARCHAR(255) NOT NULL,
            user_id INTEGER,
            created_at DATETIME NOT NULL
        )
        """
    )

    # costing tables
    if not table_exists(cur, "costing_template_profiles"):
        cur.execute(
            """
            CREATE TABLE costing_template_profiles (
                id INTEGER PRIMARY KEY,
                engine_template_id INTEGER,
                name VARCHAR(255) NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                xlsx_template_path VARCHAR(512),
                sheet_name VARCHAR(128),
                table_start_row INTEGER,
                required_columns_json JSON,
                header_cell_map_json JSON,
                row_match_keys_json JSON,
                programme_rules_json JSON,
                created_by_id INTEGER,
                created_at DATETIME
            )
            """
        )
        changed.append("costing_template_profiles")

    if not table_exists(cur, "costing_template_lines"):
        cur.execute(
            """
            CREATE TABLE costing_template_lines (
                id INTEGER PRIMARY KEY,
                costing_template_profile_id INTEGER NOT NULL,
                line_no INTEGER,
                group_no VARCHAR(64),
                figure VARCHAR(64),
                item_no VARCHAR(64),
                oem_part_no VARCHAR(120),
                system_part_number VARCHAR(120),
                part_description VARCHAR(255),
                default_class VARCHAR(64),
                default_intended_supplier VARCHAR(128),
                default_latest_supplier VARCHAR(128),
                default_latest_cost NUMERIC,
                default_menu_sell_price NUMERIC,
                is_menu BOOLEAN NOT NULL DEFAULT 0,
                is_kit BOOLEAN NOT NULL DEFAULT 0,
                is_consumable BOOLEAN NOT NULL DEFAULT 0,
                default_qty_on_stock INTEGER DEFAULT 0,
                default_qty_on_order INTEGER DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                updated_at DATETIME
            )
            """
        )
        changed.append("costing_template_lines")

    if not table_exists(cur, "costing_sheets"):
        cur.execute(
            """
            CREATE TABLE costing_sheets (
                id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL,
                costing_template_profile_id INTEGER,
                template_version_snapshot INTEGER,
                stage VARCHAR(64) NOT NULL DEFAULT 'awaiting_sas',
                issue VARCHAR(64),
                auth VARCHAR(64),
                job_no VARCHAR(64),
                sn VARCHAR(128),
                engine_no VARCHAR(128),
                engine_desc VARCHAR(255),
                date DATETIME,
                parts_replacement_cost NUMERIC DEFAULT 0,
                emergent_work_cost NUMERIC DEFAULT 0,
                menu_price_add NUMERIC DEFAULT 0,
                cost_booked NUMERIC DEFAULT 0,
                warning_text TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                locked_at DATETIME
            )
            """
        )
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_costing_sheets_job_id ON costing_sheets(job_id)")
        changed.append("costing_sheets")

    if not table_exists(cur, "costing_lines"):
        cur.execute(
            """
            CREATE TABLE costing_lines (
                id INTEGER PRIMARY KEY,
                costing_sheet_id INTEGER NOT NULL,
                part_requirement_id INTEGER,
                line_no INTEGER,
                group_no VARCHAR(64),
                figure VARCHAR(64),
                item_no VARCHAR(64),
                oem_part_no VARCHAR(120),
                system_part_number VARCHAR(120),
                part_description VARCHAR(255),
                line_class VARCHAR(64),
                notes TEXT,
                is_kit BOOLEAN NOT NULL DEFAULT 0,
                is_menu BOOLEAN NOT NULL DEFAULT 0,
                is_consumable BOOLEAN NOT NULL DEFAULT 0,
                intended_supplier VARCHAR(128),
                latest_supplier VARCHAR(128),
                latest_cost NUMERIC,
                price_cost NUMERIC,
                menu_sell_price_unit NUMERIC,
                rbb_value NUMERIC,
                qty_on_stock INTEGER DEFAULT 0,
                qty_on_order INTEGER DEFAULT 0,
                qty_required INTEGER DEFAULT 0,
                po_number VARCHAR(120),
                unit_cost_confirmed NUMERIC,
                line_cost NUMERIC,
                procurement_status VARCHAR(64) DEFAULT 'not_costed',
                emergent_qty_required INTEGER DEFAULT 0,
                emergent_line_cost NUMERIC,
                emergent_reason TEXT,
                match_status VARCHAR(64) DEFAULT 'unmatched_sheet',
                updated_at DATETIME
            )
            """
        )
        changed.append("costing_lines")

    conn.commit()
    conn.close()

    if changed:
        print("Added columns:", ", ".join(changed))
    else:
        print("No missing columns detected.")
    print(f"DB upgraded: {db_path}")

    if args.stamp_head:
        env = os.environ.copy()
        env.setdefault("FLASK_APP", "app:create_app")
        env["FLASK_RUN_FROM_CLI"] = "1"
        env["DATABASE_URL"] = f"sqlite:///{db_path}"
        cmd = [sys.executable, "-m", "flask", "db", "stamp", "head"]
        result = subprocess.run(cmd, env=env, check=False)
        if result.returncode != 0:
            print("Alembic stamp failed. You can run: flask db stamp head")
            return result.returncode
        print("Alembic stamped to head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
