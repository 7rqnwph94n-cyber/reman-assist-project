from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from models import db, MeasurementResultEnum, MeasurementAuditLog


MM_PER_INCH = Decimal("25.4")
LBFT_PER_NM = Decimal("0.7375621492772656")


def _clean_numeric(raw: Any) -> str:
    text = ("" if raw is None else str(raw)).strip()
    cleaned = "".join(ch for ch in text if (ch.isdigit() or ch == "."))
    return cleaned


def _to_decimal(raw: Any) -> Decimal | None:
    cleaned = _clean_numeric(raw)
    if not cleaned:
        return None
    if cleaned.count(".") > 1:
        raise ValueError("Invalid numeric value.")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid numeric value.")


def _format_decimal(val: Decimal | None, precision: str = "0.0001") -> str | None:
    if val is None:
        return None
    q = Decimal(precision)
    return f"{val.quantize(q, rounding=ROUND_HALF_UP):.4f}"


def _normalize_unit(unit: str | None) -> str:
    return (unit or "").strip()


def convert_units(value: Decimal, from_unit: str | None, to_unit: str | None) -> Decimal:
    from_u = _normalize_unit(from_unit).lower()
    to_u = _normalize_unit(to_unit).lower()
    if not from_u or not to_u or from_u == to_u:
        return value

    if from_u in {"mm", "millimeter", "millimetre"} and to_u in {"in", "inch", "inches"}:
        return value / MM_PER_INCH
    if from_u in {"in", "inch", "inches"} and to_u in {"mm", "millimeter", "millimetre"}:
        return value * MM_PER_INCH

    if from_u in {"nm"} and to_u in {"lb-ft", "lbft", "ft-lb", "ftlb"}:
        return value * LBFT_PER_NM
    if from_u in {"lb-ft", "lbft", "ft-lb", "ftlb"} and to_u in {"nm"}:
        return value / LBFT_PER_NM

    return value


def _is_clearance_label(label: str | None) -> bool:
    if not label:
        return False
    text = label.lower()
    return "clearance" in text or "tolerance" in text


def validate_and_format_measurement(
    raw_value: Any,
    spec_min: Any,
    spec_max: Any,
    unit: str | None,
    label: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"value": None, "result": MeasurementResultEnum.NOT_MEASURED, "error": None}

    try:
        value = _to_decimal(raw_value)
        min_val = _to_decimal(spec_min)
        max_val = _to_decimal(spec_max)
    except ValueError:
        result["error"] = "Invalid measurement value."
        return result

    unit_norm = _normalize_unit(unit)
    if value is not None and _is_clearance_label(label):
        ceiling = Decimal("2.0") if "in" in unit_norm.lower() else Decimal("50.0")
        if value > ceiling:
            result["error"] = "Data Entry Error: clearance/tolerance exceeds hard ceiling."
            return result

    if value is None:
        result["result"] = MeasurementResultEnum.NOT_MEASURED
    elif min_val is not None and max_val is not None and min_val <= value <= max_val:
        result["result"] = MeasurementResultEnum.WITHIN_SPEC
    elif min_val is None or max_val is None:
        result["result"] = MeasurementResultEnum.NOT_MEASURED
    else:
        result["result"] = MeasurementResultEnum.OUT_OF_SPEC

    result["value"] = value
    result["min"] = min_val
    result["max"] = max_val
    result["unit"] = unit_norm
    result["value_str"] = _format_decimal(value)
    result["min_str"] = _format_decimal(min_val)
    result["max_str"] = _format_decimal(max_val)
    return result


def apply_measurement_to_survey_item(
    *,
    item,
    raw_value: Any,
    spec_min: Any,
    spec_max: Any,
    unit: str | None,
    label: str | None = None,
    user=None,
    change_reason: str | None = None,
) -> dict[str, Any]:
    outcome = validate_and_format_measurement(raw_value, spec_min, spec_max, unit, label=label)
    if outcome.get("error"):
        return outcome

    old_value = item.measurement_value
    old_unit = item.measurement_unit

    item.measurement_value = outcome.get("value_str")
    item.spec_min = outcome.get("min_str")
    item.spec_max = outcome.get("max_str")
    item.measurement_unit = outcome.get("unit") or None
    item.measurement_result = outcome.get("result")

    if old_value != item.measurement_value:
        db.session.add(
            MeasurementAuditLog(
                survey_item_id=item.id,
                user_id=user.id if user else None,
                field_name="measurement_value",
                old_value=old_value,
                new_value=item.measurement_value,
                change_reason=change_reason,
            )
        )
    if old_unit != item.measurement_unit:
        db.session.add(
            MeasurementAuditLog(
                survey_item_id=item.id,
                user_id=user.id if user else None,
                field_name="measurement_unit",
                old_value=old_unit,
                new_value=item.measurement_unit,
                change_reason=change_reason,
            )
        )

    return outcome


def normalize_decimal_field(raw_value: Any) -> tuple[Decimal | None, str | None]:
    value = _to_decimal(raw_value)
    return value, _format_decimal(value)
