"""Shared illustration helper functions.

Extracted from illustrations/routes.py to break the cross-blueprint import
between templates/routes.py and illustrations/routes.py.
"""
from __future__ import annotations

import csv
import io
import os
import re

from flask import current_app


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

def _normalize_header(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower())
    return clean.strip("_")


def _coerce_int(val):
    if val is None:
        return None
    if isinstance(val, (int,)):
        return val
    if isinstance(val, float):
        return int(val) if val.is_integer() else None
    text = str(val).strip()
    if not text:
        return None
    text = text.replace(",", "")
    if re.fullmatch(r"\d+", text):
        return int(text)
    if re.fullmatch(r"\d+(\.\d+)?", text):
        try:
            num = float(text)
        except ValueError:
            return None
        return int(num) if num.is_integer() else None
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _normalize_section_key(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "", (value or "").strip())
    return clean.upper()


def _strip_prefix_variants(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    variants = {raw}
    upper = raw.upper().replace("_", " ").strip()
    variants.add(upper)
    for prefix in ("OEM PDF", "OEMPDF", "PDF"):
        if upper.startswith(prefix):
            tail = upper[len(prefix):].strip(" -_.")
            if tail:
                variants.add(tail)
    return list(variants)


# ---------------------------------------------------------------------------
# CSV / text parsing
# ---------------------------------------------------------------------------

def _parse_parts_from_text(raw_text: str) -> tuple[list[list[str]], list[str]]:
    if not raw_text:
        return [], []
    raw_text = raw_text.strip()
    if not raw_text:
        return [], []
    sample = raw_text.splitlines()[:5]
    delimiter = "\t" if any("\t" in line for line in sample) else ","
    reader = csv.reader(io.StringIO(raw_text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return [], []
    header = [_normalize_header(cell) for cell in rows[0]]
    return rows, header


# ---------------------------------------------------------------------------
# PDF extractor helpers
# ---------------------------------------------------------------------------

def _get_pdf_extractor():
    try:
        from pdf_parts_extractor.extract import run_extract  # type: ignore
        from pdf_parts_extractor.profiles import list_profiles  # type: ignore
    except Exception as exc:
        return None, None, exc
    return run_extract, list_profiles, None


def _list_pdf_profiles() -> tuple[list[str], str | None]:
    _, list_profiles, err = _get_pdf_extractor()
    if not list_profiles:
        return [], f"PDF extractor not available: {err}" if err else "PDF extractor not available."
    try:
        raw = [p for p in list_profiles() if p]
        profiles = sorted({os.path.basename(p) for p in raw})
    except Exception as exc:
        return [], f"Unable to list profiles: {exc}"
    return profiles, None


# ---------------------------------------------------------------------------
# Legacy section image lookup
# ---------------------------------------------------------------------------

def _find_legacy_section_image(template, section_name: str) -> str | None:
    upload_root = current_app.config["UPLOAD_FOLDER"]
    img_root = os.path.join(upload_root, "section_images")
    search_dirs = []
    if template.engine_type:
        search_dirs.append(os.path.join(img_root, template.engine_type))
    search_dirs.append(os.path.join(img_root, "generic"))
    if os.path.isdir(img_root):
        for entry in os.listdir(img_root):
            cand = os.path.join(img_root, entry)
            if os.path.isdir(cand):
                search_dirs.append(cand)
    search_dirs.append(img_root)
    allowed_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    section_name = (section_name or "").strip()
    normalized_target = _normalize_section_key(section_name)
    targets = {normalized_target}
    for variant in _strip_prefix_variants(section_name):
        targets.add(_normalize_section_key(variant))
    match = re.match(r"^([A-Za-z]{1,4})\s*-?\s*(\d{2,4})", section_name)
    if match:
        code = f"{match.group(1).upper()}{match.group(2)}"
        targets.add(_normalize_section_key(code))

    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            base, ext = os.path.splitext(fname)
            if ext.lower() not in allowed_exts:
                continue
            if re.search(r"\\bcont\\b", base.lower()):
                continue
            clean = base.strip()
            pretty = clean.replace("_", " ").strip()
            candidates = {
                _normalize_section_key(clean),
                _normalize_section_key(pretty),
            }
            for variant in _strip_prefix_variants(pretty):
                candidates.add(_normalize_section_key(variant))
            for match in re.findall(r"[A-Za-z]{1,4}\s*\d{2,4}", pretty):
                code = re.sub(r"\s+", "", match).upper()
                candidates.add(_normalize_section_key(code))
            if candidates & targets:
                abs_path = os.path.join(directory, fname)
                return os.path.relpath(abs_path, upload_root).replace("\\", "/")
            match = re.match(r"^([A-Za-z]{1,4})\s*-?\s*(\d{2,4})", pretty)
            if match:
                code = f"{match.group(1).upper()}{match.group(2)}"
                if normalized_target == _normalize_section_key(code):
                    abs_path = os.path.join(directory, fname)
                    return os.path.relpath(abs_path, upload_root).replace("\\", "/")
    return None


# ---------------------------------------------------------------------------
# Column extraction from parsed rows
# ---------------------------------------------------------------------------

def _extract_columns(rows: list[list[str]], mapping: dict[str, int]) -> list[dict]:
    out = []
    for row in rows:
        pos_idx = mapping.get("pos")
        part_idx = mapping.get("part_no")
        qty_idx = mapping.get("qty")
        des_idx = mapping.get("designation")
        pos_raw = row[pos_idx].strip() if pos_idx is not None and pos_idx < len(row) else ""
        part_no = row[part_idx].strip() if part_idx is not None and part_idx < len(row) else ""
        qty_raw = row[qty_idx].strip() if qty_idx is not None and qty_idx < len(row) else ""
        designation = row[des_idx].strip() if des_idx is not None and des_idx < len(row) else ""

        pos = _coerce_int(pos_raw)
        qty = _coerce_int(qty_raw) or 1

        out.append(
            {
                "pos": pos,
                "part_no": part_no or None,
                "qty": qty,
                "designation": designation or None,
            }
        )
    return out


def _extract_columns_by_header(rows: list[list[str]], header: list[str], column_map: dict[str, str]) -> list[dict]:
    header_map = {name: idx for idx, name in enumerate(header)}
    designation_name = _normalize_header(column_map.get("designation", "designation"))
    if designation_name not in header_map and "name" in header_map:
        designation_name = "name"
    wanted = {
        "pos": _normalize_header(column_map.get("pos", "pos")),
        "part_no": _normalize_header(column_map.get("part_no", "part_no")),
        "qty": _normalize_header(column_map.get("qty", "qty")),
        "designation": designation_name,
    }
    mapping = {}
    for key, header_name in wanted.items():
        if header_name in header_map:
            mapping[key] = header_map[header_name]
    if not mapping:
        return []
    return _extract_columns(rows, mapping)


def _extract_columns_with_shift(rows: list[list[str]]) -> list[dict]:
    mapping = {"pos": 0, "part_no": 1, "qty": 2, "designation": 3}
    parsed = _extract_columns(rows, mapping)
    if not parsed:
        return []
    if parsed[0].get("pos") is not None:
        return [row for row in parsed if row.get("pos") is not None or row.get("part_no") or row.get("designation")]
    shifted = _extract_columns(rows, {"pos": 1, "part_no": 2, "qty": 3, "designation": 4})
    return [row for row in shifted if row.get("pos") is not None or row.get("part_no") or row.get("designation")]


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def _extract_rows_from_pdf_text(text: str) -> list[dict]:
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    part_pattern = re.compile(r"^\d{2}\.\d{5}-\d{4}$")
    item_pattern = re.compile(r"^\d{1,3}$")
    qty_pattern = re.compile(r"^\d{1,4}([,.]\d{1,2})?$")

    def _next_nonempty(start: int) -> str | None:
        for j in range(start, len(lines)):
            if lines[j]:
                return lines[j]
        return None

    def _is_new_pos(line: str, next_line: str | None) -> bool:
        return bool(item_pattern.match(line) and next_line and part_pattern.match(next_line))

    rows = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        next_line = _next_nonempty(idx + 1)

        if _is_new_pos(line, next_line):
            pos = _coerce_int(line)
            block = []
            j = idx + 1
            while j < len(lines):
                if _is_new_pos(lines[j], _next_nonempty(j + 1)):
                    break
                block.append(lines[j])
                j += 1

            part_no = None
            part_idx = None
            for k, entry in enumerate(block):
                if part_pattern.match(entry):
                    part_no = entry
                    part_idx = k
                    break

            if part_no is not None:
                after_part = block[part_idx + 1:] if part_idx is not None else []
                qty = None
                qty_idx = None
                for k, entry in enumerate(after_part):
                    if qty_pattern.match(entry):
                        qty = _coerce_int(entry)
                        qty_idx = k
                        break

                if qty_idx is not None:
                    designation = [l for l in after_part[qty_idx + 1:] if l.strip()]
                else:
                    qty_line_idx = None
                    qty_line_desc = None
                    for k, entry in enumerate(after_part):
                        match = re.match(r"^(\d{1,4})([,.]\d{1,2})?\s+(.+)$", entry)
                        if match:
                            qty_line_idx = k
                            qty_line_desc = match.group(3)
                            qty_text = f"{match.group(1)}{match.group(2) or ''}"
                            qty = _coerce_int(qty_text)
                            break
                    if qty_line_idx is not None:
                        designation = [qty_line_desc] + [
                            l for l in after_part[qty_line_idx + 1:] if l.strip()
                        ]
                    else:
                        designation = [l for l in after_part if not qty_pattern.match(l)]

                if designation:
                    rows.append(
                        {
                            "pos": pos,
                            "part_no": part_no,
                            "qty": qty or 1,
                            "designation": " ".join(designation).strip(),
                        }
                    )
            idx = j
            continue

        idx += 1

    if rows:
        return rows

    rows = [re.split(r"\s{2,}", line) for line in lines]
    header = [_normalize_header(cell) for cell in rows[0]]
    extracted = []
    if header and "pos" in header:
        extracted = _extract_columns_by_header(
            rows[1:], header, {"pos": "pos", "part_no": "part_no", "qty": "qty", "designation": "designation"}
        )
    if not extracted:
        extracted = _extract_columns_with_shift(rows)
    return extracted


def _extract_section_heading(text: str) -> str | None:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    part_pattern = re.compile(r"^\d{2}\.\d{5}-\d{4}$")
    item_pattern = re.compile(r"^\d{1,3}$")

    def _next_nonempty(start: int) -> str | None:
        for j in range(start, len(lines)):
            if lines[j]:
                return lines[j]
        return None

    first_pos_idx = None
    for i, line in enumerate(lines):
        next_line = _next_nonempty(i + 1)
        if item_pattern.match(line) and next_line and part_pattern.match(next_line):
            first_pos_idx = i
            break

    header_lines = lines[:first_pos_idx] if first_pos_idx is not None else lines[:20]
    for line in reversed(header_lines):
        if any(ch.isdigit() for ch in line):
            continue
        if len(line) < 3:
            continue
        if line.upper() != line:
            continue
        if not any(ch.isalpha() for ch in line):
            continue
        cleaned = re.sub(r"\bCONT(INUED)?\b", "", line).strip(" -/").strip()
        return cleaned or None
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_parts(rows: list[dict]) -> list[str]:
    errors = []
    seen = set()
    for row in rows:
        pos = row.get("pos")
        if pos is None:
            if not (row.get("part_no") or row.get("designation")):
                continue
            errors.append("POS must be an integer.")
            continue
        if pos in seen:
            errors.append(f"Duplicate POS detected: {pos}.")
            continue
        seen.add(pos)
    return errors
