import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


TERMS = {
    "UK": {
        "work_order": "Job pack",
        "work_orders": "Job packs",
        "work_order_caps": "Job Pack",
        "work_order_lower": "job pack",
        "work_order_id": "Job pack ID",
        "parts_list": "BOM",
        "parts_list_caps": "BOM",
        "parts_list_lower": "parts list",
        "parts_list_lines": "BOM lines",
        "parts_list_and": "Parts / BOM",
        "parts_list_label": "BOM",
        "parts_list_required": "Parts required",
        "inspection": "survey",
        "inspection_caps": "Survey",
        "inspection_upper": "SURVEY",
        "inspections": "surveys",
        "pre_inspection": "Pre-survey",
        "pre_inspection_lower": "pre-survey",
        "strip_inspection": "Strip survey",
        "strip_inspection_lower": "strip survey",
        "inspection_line": "survey line",
        "inspection_lines": "survey lines",
        "inspection_time": "Survey time",
        "inspection_findings": "Survey findings",
        "inspection_results": "Survey results",
        "inspection_by": "Survey by",
        "inspection_completed": "Survey completed",
        "inspection_updated": "Survey updated",
        "inspection_read_only": "Survey is read-only at this stage.",
        "inspection_locked": "Survey edits are locked once the job reaches Office/Build.",
        "inspection_changed": "Survey has changed on another terminal.",
        "inspection_complete_send": "Complete survey & send to office",
        "inspection_init": "Initialize survey",
        "inspection_open": "Open survey",
        "inspection_add_line": "Add survey line",
        "inspection_summary": "Strip survey summary",
        "inspection_total_lines": "Total survey lines",
        "inspection_precheck": "Pre-survey check",
        "inspection_precheck_sub": "Quick as-received check before full strip survey.",
        "inspection_precheck_save": "Save pre-survey and continue to strip survey",
        "inspection_no_precheck": "No pre-survey checklist defined for this template. You can still add notes below.",
        "parts_room": "Stores",
        "parts_room_lower": "stores",
        "parts_room_master": "Stores – Master list",
        "parts_room_by_engine": "Stores – By engine",
        "parts_room_consumables": "Stores – Consumables",
        "parts_room_barcode": "Stores – Barcode setup",
        "parts_room_picklist": "Stores – Pick list inbox",
        "parts_room_template": "Stores – {name}",
        "stores_updates_by": "Stores updates by",
        "bind_costing": "Bind costing to BOM",
        "back_to_parts": "← Back to BOM",
        "costing_sheet": "Costing sheet",
        "audit_trail": "Revision History",
        "asset_technical_file": "Component Summary",
    },
    "US": {
        "work_order": "Work Order",
        "work_orders": "Work Orders",
        "work_order_caps": "Work Order",
        "work_order_lower": "work order",
        "work_order_id": "Work Order ID",
        "parts_list": "Parts List",
        "parts_list_caps": "Parts List",
        "parts_list_lower": "parts list",
        "parts_list_lines": "Parts List lines",
        "parts_list_and": "Parts List",
        "parts_list_label": "Parts List",
        "parts_list_required": "Parts required",
        "inspection": "inspection",
        "inspection_caps": "Inspection",
        "inspection_upper": "INSPECTION",
        "inspections": "inspections",
        "pre_inspection": "Pre-inspection",
        "pre_inspection_lower": "pre-inspection",
        "strip_inspection": "Strip inspection",
        "strip_inspection_lower": "strip inspection",
        "inspection_line": "inspection line",
        "inspection_lines": "inspection lines",
        "inspection_time": "Inspection time",
        "inspection_findings": "Inspection findings",
        "inspection_results": "Inspection results",
        "inspection_by": "Inspection by",
        "inspection_completed": "Inspection completed",
        "inspection_updated": "Inspection updated",
        "inspection_read_only": "Inspection is read-only at this stage.",
        "inspection_locked": "Inspection edits are locked once the job reaches Office/Build.",
        "inspection_changed": "Inspection has changed on another terminal.",
        "inspection_complete_send": "Complete inspection & send to office",
        "inspection_init": "Initialize inspection",
        "inspection_open": "Open inspection",
        "inspection_add_line": "Add inspection line",
        "inspection_summary": "Strip inspection summary",
        "inspection_total_lines": "Total inspection lines",
        "inspection_precheck": "Pre-inspection check",
        "inspection_precheck_sub": "Quick as-received check before full strip inspection.",
        "inspection_precheck_save": "Save pre-inspection and continue to strip inspection",
        "inspection_no_precheck": "No pre-inspection checklist defined for this template. You can still add notes below.",
        "parts_room": "Parts Room",
        "parts_room_lower": "parts room",
        "parts_room_master": "Parts Room – Master list",
        "parts_room_by_engine": "Parts Room – By engine",
        "parts_room_consumables": "Parts Room – Consumables",
        "parts_room_barcode": "Parts Room – Barcode setup",
        "parts_room_picklist": "Parts Room – Pick list inbox",
        "parts_room_template": "Parts Room – {name}",
        "stores_updates_by": "Parts Room updates by",
        "bind_costing": "Bind costing to Parts List",
        "back_to_parts": "← Back to Parts List",
        "costing_sheet": "Costing sheet",
        "audit_trail": "Audit Trail & Compliance Log",
        "asset_technical_file": "Asset Technical File",
    },
}


def _safe_upper(val: str | None) -> str | None:
    if val is None:
        return None
    return str(val).upper()


def get_region() -> str:
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            region = current_app.config.get("REGION")
            if region:
                return _safe_upper(region) or "UK"
    except Exception:
        pass
    return _safe_upper(os.environ.get("REGION")) or "UK"


def get_locale() -> str:
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            locale = current_app.config.get("LOCALE")
            if locale:
                return str(locale)
    except Exception:
        pass
    return os.environ.get("LOCALE") or "en_GB"


def get_currency() -> str:
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            currency = current_app.config.get("CURRENCY")
            if currency:
                return str(currency)
    except Exception:
        pass
    return os.environ.get("CURRENCY") or "GBP"


def t(key: str, default: str | None = None) -> str:
    region = get_region()
    region_terms = TERMS.get(region, TERMS.get("UK", {}))
    if key in region_terms:
        return region_terms[key]
    if default is not None:
        return default
    return key


def _parse_decimal(val: Any) -> Decimal | None:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def format_date(
    dt: Any,
    with_time: bool = True,
    fallback: str = "—",
) -> str:
    if not dt:
        return fallback
    if isinstance(dt, str):
        return dt
    if not isinstance(dt, datetime):
        try:
            dt = datetime.fromisoformat(str(dt))
        except Exception:
            return fallback

    region = get_region()
    if region == "US":
        date_fmt = "%m/%d/%Y"
    else:
        date_fmt = "%d/%m/%Y"

    if with_time:
        return dt.strftime(f"{date_fmt} %H:%M")
    return dt.strftime(date_fmt)


def format_currency(amount: Any, fallback: str = "—") -> str:
    if amount is None or amount == "":
        return fallback
    value = _parse_decimal(amount)
    if value is None:
        return fallback
    region = get_region()
    symbol = "$" if region == "US" else "£"
    return f"{symbol}{value:,.2f}"


def _normalize_unit(unit: str | None) -> str:
    if not unit:
        return ""
    return str(unit).strip().lower()


def format_units(
    value: Any,
    unit_type: str = "length",
    unit: str | None = None,
    precision: int | None = None,
    include_unit: bool = True,
    fallback: str = "—",
) -> str:
    if value is None or value == "":
        return fallback
    val = _parse_decimal(value)
    if val is None:
        return fallback

    unit_norm = _normalize_unit(unit)
    region = get_region()

    if unit_type == "length" and region == "US":
        if unit_norm in {"mm", "millimeter", "millimetre", "millimeters", "millimetres"}:
            val = val / Decimal("25.4")
            unit_norm = "in"
        if unit_norm in {"thou", "thousandth"}:
            val = val / Decimal("1000")
            unit_norm = "in"

    if precision is None:
        precision = 4 if unit_type == "length" else 2

    fmt = f"{{:.{precision}f}}"
    num = fmt.format(val)
    if include_unit and unit_norm:
        return f"{num} {unit_norm}"
    return num


def unit_hint(unit_type: str = "length") -> str:
    region = get_region()
    if unit_type == "length" and region == "US":
        return "in (thou ok)"
    return "mm"


def localization_self_check() -> dict[str, dict[str, str]]:
    return {
        "UK": {
            "work_order": TERMS["UK"].get("work_order", ""),
            "parts_list": TERMS["UK"].get("parts_list", ""),
            "inspection": TERMS["UK"].get("inspection_caps", ""),
            "parts_room": TERMS["UK"].get("parts_room", ""),
        },
        "US": {
            "work_order": TERMS["US"].get("work_order", ""),
            "parts_list": TERMS["US"].get("parts_list", ""),
            "inspection": TERMS["US"].get("inspection_caps", ""),
            "parts_room": TERMS["US"].get("parts_room", ""),
        },
    }
