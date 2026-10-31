#!/usr/bin/env python3
"""
Verify row-level tenant hardening for store_items / pick_lists / pick_list_items.

Usage:
  PYTHONPATH=. python3 scripts/verify_tenant_hardening.py
  PYTHONPATH=. python3 scripts/verify_tenant_hardening.py --exercise-unique
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app import create_app
from models import db, Organization, Template, TemplateItem, StoreItem


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str


def _pass(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, ok=True, details=details)


def _fail(name: str, details: str) -> CheckResult:
    return CheckResult(name=name, ok=False, details=details)


def _table_has_column(insp, table: str, column: str) -> bool:
    return column in {c["name"] for c in insp.get_columns(table)}


def _table_has_not_null(insp, table: str, column: str) -> bool:
    for c in insp.get_columns(table):
        if c["name"] == column:
            return not c["nullable"]
    return False


def _table_has_index(insp, table: str, index_name: str) -> bool:
    return index_name in {i["name"] for i in insp.get_indexes(table)}


def _table_has_fk(insp, table: str, fk_name: str) -> bool:
    return fk_name in {f["name"] for f in insp.get_foreign_keys(table)}


def _table_has_unique(insp, table: str, cols: tuple[str, ...], name: str) -> bool:
    names = {u["name"] for u in insp.get_unique_constraints(table)}
    if name in names:
        return True
    cols_set = set(cols)
    for u in insp.get_unique_constraints(table):
        if set(u.get("column_names") or []) == cols_set:
            return True
    return False


def run_checks(exercise_unique: bool) -> int:
    app = create_app()
    results: list[CheckResult] = []

    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        dialect = engine.dialect.name

        print(f"DB backend: {dialect}")
        print(f"DB URL: {engine.url}")

        for table in ("store_items", "pick_lists", "pick_list_items"):
            has_col = _table_has_column(insp, table, "organization_id")
            results.append(
                _pass(f"{table}.organization_id exists", "column present")
                if has_col
                else _fail(f"{table}.organization_id exists", "column missing")
            )

            not_null = _table_has_not_null(insp, table, "organization_id")
            results.append(
                _pass(f"{table}.organization_id NOT NULL", "NOT NULL enforced")
                if not_null
                else _fail(f"{table}.organization_id NOT NULL", "nullable or missing")
            )

        fk_expectations = [
            ("store_items", "fk_store_items_organization_id"),
            ("pick_lists", "fk_pick_lists_organization_id"),
            ("pick_list_items", "fk_pick_list_items_organization_id"),
        ]
        for table, fk_name in fk_expectations:
            ok = _table_has_fk(insp, table, fk_name)
            results.append(
                _pass(f"{table} FK -> organizations", fk_name)
                if ok
                else _fail(f"{table} FK -> organizations", f"missing FK {fk_name}")
            )

        idx_expectations = [
            ("store_items", "ix_store_items_organization_id"),
            ("pick_lists", "ix_pick_lists_organization_id"),
            ("pick_list_items", "ix_pick_list_items_organization_id"),
        ]
        for table, idx_name in idx_expectations:
            ok = _table_has_index(insp, table, idx_name)
            results.append(
                _pass(f"{table} org index", idx_name)
                if ok
                else _fail(f"{table} org index", f"missing index {idx_name}")
            )

        uq_ok = _table_has_unique(
            insp,
            "store_items",
            ("organization_id", "barcode"),
            "uq_store_items_org_barcode",
        )
        results.append(
            _pass("store_items UNIQUE(org, barcode)", "constraint present")
            if uq_ok
            else _fail("store_items UNIQUE(org, barcode)", "constraint missing")
        )

        # Data population checks
        for table in ("store_items", "pick_lists", "pick_list_items"):
            if has_col:
                missing = db.session.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE organization_id IS NULL")
                ).scalar_one()
                results.append(
                    _pass(f"{table} org backfill", "no NULL organization_id rows")
                    if missing == 0
                    else _fail(f"{table} org backfill", f"{missing} row(s) missing organization_id")
                )
            else:
                results.append(_fail(f"{table} org backfill", "organization_id column missing"))

        # Chain consistency checks
        if _table_has_column(insp, "store_items", "organization_id"):
            mismatched_store = db.session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM store_items s
                    JOIN template_items ti ON ti.id = s.template_item_id
                    WHERE s.organization_id != ti.organization_id
                    """
                )
            ).scalar_one()
            results.append(
                _pass("StoreItem -> TemplateItem org chain", "all rows consistent")
                if mismatched_store == 0
                else _fail("StoreItem -> TemplateItem org chain", f"{mismatched_store} mismatch row(s)")
            )
        else:
            results.append(_fail("StoreItem -> TemplateItem org chain", "organization_id column missing on store_items"))

        if _table_has_column(insp, "pick_lists", "organization_id"):
            mismatched_picklist = db.session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM pick_lists p
                    JOIN jobs j ON j.id = p.job_id
                    WHERE p.organization_id != j.organization_id
                    """
                )
            ).scalar_one()
            results.append(
                _pass("PickList -> Job org chain", "all rows consistent")
                if mismatched_picklist == 0
                else _fail("PickList -> Job org chain", f"{mismatched_picklist} mismatch row(s)")
            )
        else:
            results.append(_fail("PickList -> Job org chain", "organization_id column missing on pick_lists"))

        if _table_has_column(insp, "pick_list_items", "organization_id"):
            mismatched_pickitem = db.session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM pick_list_items pi
                    JOIN pick_lists p ON p.id = pi.pick_list_id
                    WHERE pi.organization_id != p.organization_id
                    """
                )
            ).scalar_one()
            results.append(
                _pass("PickListItem -> PickList org chain", "all rows consistent")
                if mismatched_pickitem == 0
                else _fail("PickListItem -> PickList org chain", f"{mismatched_pickitem} mismatch row(s)")
            )
        else:
            results.append(
                _fail("PickListItem -> PickList org chain", "organization_id column missing on pick_list_items")
            )

        # Optional write-probe for uniqueness behavior.
        if exercise_unique:
            try:
                org_a = Organization.query.order_by(Organization.id.asc()).first()
                org_b = Organization.query.order_by(Organization.id.desc()).first()
                if not org_a:
                    raise RuntimeError("No organizations found")
                if not org_b or org_b.id == org_a.id:
                    org_b = Organization(name="verify-org-b", slug="verify-org-b")
                    db.session.add(org_b)
                    db.session.flush()

                tpl_a = Template(name="verify-tpl-a", engine_type="verify", organization_id=org_a.id)
                tpl_b = Template(name="verify-tpl-b", engine_type="verify", organization_id=org_b.id)
                db.session.add_all([tpl_a, tpl_b])
                db.session.flush()

                ti_a = TemplateItem(template_id=tpl_a.id, organization_id=org_a.id, section="A", pos=1, part_no="V-A", name="V-A", qty=1)
                ti_b = TemplateItem(template_id=tpl_b.id, organization_id=org_b.id, section="A", pos=1, part_no="V-B", name="V-B", qty=1)
                db.session.add_all([ti_a, ti_b])
                db.session.flush()

                s1 = StoreItem(template_item_id=ti_a.id, organization_id=org_a.id, barcode="TENANT-VERIFY-1")
                s2 = StoreItem(template_item_id=ti_b.id, organization_id=org_b.id, barcode="TENANT-VERIFY-1")
                db.session.add_all([s1, s2])
                db.session.flush()
                results.append(_pass("barcode cross-org duplicate", "allowed as expected"))

                dup_same_org = StoreItem(template_item_id=ti_a.id, organization_id=org_a.id, barcode="TENANT-VERIFY-1")
                db.session.add(dup_same_org)
                try:
                    db.session.flush()
                    results.append(_fail("barcode same-org duplicate", "unexpectedly allowed"))
                except IntegrityError:
                    db.session.rollback()
                    results.append(_pass("barcode same-org duplicate", "rejected as expected"))
            except Exception as exc:
                db.session.rollback()
                results.append(_fail("barcode uniqueness write-probe", str(exc)))
            finally:
                db.session.rollback()

    failures = [r for r in results if not r.ok]
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        print(f"[{status}] {r.name} :: {r.details}")

    if failures:
        print(f"\nRESULT: FAIL ({len(failures)} check(s) failed)")
        return 1
    print("\nRESULT: PASS (all checks passed)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exercise-unique",
        action="store_true",
        help="Run write-probe for barcode uniqueness in a rollback transaction.",
    )
    args = parser.parse_args()
    return run_checks(exercise_unique=args.exercise_unique)


if __name__ == "__main__":
    raise SystemExit(main())
