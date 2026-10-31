import csv
import io
import os
import re
import tempfile
import time
from datetime import datetime, timezone

import pandas as pd
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for, current_app
from werkzeug.utils import secure_filename

from auth_utils import login_required, roles_required, current_user, get_org_filter, get_scoped_or_404
from file_utils import (
    save_uploaded_file,
    validate_upload,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_TYPES,
    ALLOWED_TEMPLATE_IMPORT_EXTENSIONS,
    ALLOWED_TEMPLATE_IMPORT_MIME_TYPES,
    ALLOWED_PDF_EXTENSIONS,
    ALLOWED_PDF_MIME_TYPES,
)
from models import (
    db,
    RoleEnum,
    Template,
    TemplateItem,
    TemplateSection,
    IllustrationPage,
    IllustrationPartRow,
    IllustrationPosLabel,
    IllustrationHotspot,
    TemplateSectionIllustrationLink,
)
from services.job_services import log_event
from services.pdf_import import render_cropped_page
from services.illustration_helpers import (
    _normalize_header,
    _coerce_int,
    _parse_parts_from_text,
    _get_pdf_extractor,
    _list_pdf_profiles,
    _normalize_section_key,
    _strip_prefix_variants,
    _find_legacy_section_image,
    _extract_columns,
    _extract_columns_by_header,
    _extract_columns_with_shift,
    _extract_rows_from_pdf_text,
    _extract_section_heading,
    _validate_parts,
)


illustrations_bp = Blueprint("illustrations_bp", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)


def _get_illustration_page_for_template(page_id, template):
    """Fetch an IllustrationPage by ID, verifying it belongs to the given template via section links."""
    try:
        pid = int(page_id)
    except (TypeError, ValueError):
        return None
    page = (
        IllustrationPage.query
        .join(TemplateSectionIllustrationLink, TemplateSectionIllustrationLink.illustration_page_id == IllustrationPage.id)
        .join(TemplateSection, TemplateSection.id == TemplateSectionIllustrationLink.template_section_id)
        .filter(IllustrationPage.id == pid, TemplateSection.template_id == template.id)
        .first()
    )
    return page


def _ensure_template_sections(template: Template, items: list[TemplateItem]) -> dict[str, TemplateSection]:
    ordered_names = []
    for item in items:
        name = (item.section or "General").strip() or "General"
        if name not in ordered_names:
            ordered_names.append(name)

    existing = {
        s.name: s
        for s in TemplateSection.query.filter_by(template_id=template.id).all()
    }
    section_map = {}
    for idx, name in enumerate(ordered_names, start=1):
        sec = existing.get(name)
        if not sec:
            sec = TemplateSection(template_id=template.id, name=name, display_order=idx)
            db.session.add(sec)
            db.session.flush()
        else:
            if sec.display_order != idx:
                sec.display_order = idx
        section_map[name] = sec

    db.session.commit()
    return section_map


def _load_parts_from_upload(uploaded, column_map: dict[str, str]) -> list[dict]:
    validate_upload(
        uploaded,
        allowed_exts=ALLOWED_TEMPLATE_IMPORT_EXTENSIONS,
        allowed_mimetypes=ALLOWED_TEMPLATE_IMPORT_MIME_TYPES,
    )

    filename = (uploaded.filename or "").lower()
    raw_bytes = uploaded.read()
    try:
        raw_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode("latin1")
    if filename.endswith(".csv"):
        df = pd.read_csv(io.StringIO(raw_text), sep=None, engine="python")
    else:
        df = pd.read_excel(io.BytesIO(raw_bytes))
    df.columns = [str(c).strip().lower() for c in df.columns]
    normalized_cols = {_normalize_header(c): c for c in df.columns}

    if len(df.columns) == 1 and ("\t" in df.columns[0] or "\t" in raw_text):
        parsed_rows, header = _parse_parts_from_text(raw_text)
        if parsed_rows:
            if header and "pos" in header:
                rows = _extract_columns_by_header(parsed_rows[1:], header, column_map)
            else:
                rows = _extract_columns_with_shift(parsed_rows)
            return [row for row in rows if row.get("pos") is not None or row.get("part_no") or row.get("designation")]

    def col_by_candidates(candidates):
        for cand in candidates:
            key = _normalize_header(cand or "")
            if key in normalized_cols:
                return df[normalized_cols[key]]
        for cand in candidates:
            key = _normalize_header(cand or "")
            for norm_key, actual in normalized_cols.items():
                if key and key in norm_key:
                    return df[actual]
        return None

    col_pos = col_by_candidates([column_map.get("pos", "pos"), "pos", "position", "item", "item_no"])
    col_part = col_by_candidates([
        column_map.get("part_no", "part_no"),
        "part_no",
        "partno",
        "part number",
        "part_number",
        "system_part_number",
        "oem_part_no",
        "oem",
        "part",
    ])
    col_qty = col_by_candidates([column_map.get("qty", "qty"), "qty", "quantity", "qty_required"])
    col_designation = col_by_candidates([
        column_map.get("designation", "designation"),
        "designation",
        "description",
        "part_description",
        "name",
        "item description",
    ])

    if filename.endswith(".xlsx") and (col_pos is None or col_part is None):
        raw_df = pd.read_excel(io.BytesIO(raw_bytes), header=None)
        header_row = None
        for idx in range(min(len(raw_df), 10)):
            row_vals = [str(v).strip().lower() for v in raw_df.iloc[idx].tolist()]
            norm_vals = [_normalize_header(v) for v in row_vals if v]
            if any(v in {"pos", "position", "item"} for v in norm_vals) and (
                any("part" in v for v in norm_vals) or any(v in {"description", "name"} for v in norm_vals)
            ):
                header_row = idx
                break
        if header_row is not None:
            headers = [str(v).strip() for v in raw_df.iloc[header_row].tolist()]
            df = raw_df.iloc[header_row + 1 :].copy()
            df.columns = headers
            df.columns = [str(c).strip().lower() for c in df.columns]
            normalized_cols = {_normalize_header(c): c for c in df.columns}
            col_pos = col_by_candidates([column_map.get("pos", "pos"), "pos", "position", "item", "item_no"])
            col_part = col_by_candidates([
                column_map.get("part_no", "part_no"),
                "part_no",
                "partno",
                "part number",
                "part_number",
                "system_part_number",
                "oem_part_no",
                "oem",
                "part",
            ])
            col_qty = col_by_candidates([column_map.get("qty", "qty"), "qty", "quantity", "qty_required"])
            col_designation = col_by_candidates([
                column_map.get("designation", "designation"),
                "designation",
                "description",
                "part_description",
                "name",
                "item description",
            ])

    def _infer_columns(df_in):
        candidates = {}
        max_rows = min(len(df_in), 200)
        for col_name in df_in.columns:
            series = df_in[col_name].iloc[:max_rows]
            values = [str(v).strip() for v in series.tolist()]
            non_empty = [v for v in values if v not in ("", "nan", "None")]
            if not non_empty:
                continue
            numeric_vals = []
            for v in non_empty:
                if re.fullmatch(r"\d+(\.\d+)?", v.replace(",", "")):
                    numeric_vals.append(v)
            numeric_ratio = len(numeric_vals) / max(1, len(non_empty))
            avg_len = sum(len(v) for v in non_empty) / max(1, len(non_empty))
            alpha_ratio = sum(any(ch.isalpha() for ch in v) for v in non_empty) / max(1, len(non_empty))
            part_like = sum(bool(re.search(r"[A-Za-z].*\\d|\\d.*[A-Za-z]", v)) for v in non_empty) / max(1, len(non_empty))
            max_num = 0
            if numeric_vals:
                try:
                    max_num = max(float(v.replace(",", "")) for v in numeric_vals)
                except Exception:
                    max_num = 0
            candidates[col_name] = {
                "numeric_ratio": numeric_ratio,
                "alpha_ratio": alpha_ratio,
                "part_like": part_like,
                "avg_len": avg_len,
                "max_num": max_num,
            }

        def pick_pos():
            best = None
            best_score = -1
            for name, stats in candidates.items():
                score = stats["numeric_ratio"]
                if stats["max_num"] > 0 and stats["max_num"] <= 1000:
                    score += 0.2
                if score > best_score:
                    best_score = score
                    best = name
            return best

        def pick_qty():
            best = None
            best_score = -1
            for name, stats in candidates.items():
                score = stats["numeric_ratio"]
                if 0 < stats["max_num"] <= 50:
                    score += 0.3
                if score > best_score:
                    best_score = score
                    best = name
            return best

        def pick_part():
            best = None
            best_score = -1
            for name, stats in candidates.items():
                score = stats["part_like"] + (stats["numeric_ratio"] * 0.2)
                if score > best_score:
                    best_score = score
                    best = name
            return best

        def pick_desc():
            best = None
            best_score = -1
            for name, stats in candidates.items():
                score = stats["alpha_ratio"] + (stats["avg_len"] / 50.0)
                if score > best_score:
                    best_score = score
                    best = name
            return best

        return pick_pos(), pick_part(), pick_qty(), pick_desc()

    if col_pos is None or col_part is None:
        inferred = _infer_columns(df)
        if col_pos is None and inferred[0]:
            col_pos = df[inferred[0]]
        if col_part is None and inferred[1]:
            col_part = df[inferred[1]]
        if col_qty is None and inferred[2]:
            col_qty = df[inferred[2]]
        if col_designation is None and inferred[3]:
            col_designation = df[inferred[3]]

    rows = []
    for idx in range(len(df)):
        pos_val = col_pos.iloc[idx] if col_pos is not None else None
        part_no = col_part.iloc[idx] if col_part is not None else None
        qty_val = col_qty.iloc[idx] if col_qty is not None else None
        designation = col_designation.iloc[idx] if col_designation is not None else None

        pos = _coerce_int(pos_val)
        qty = _coerce_int(qty_val) or 1

        rows.append(
            {
                "pos": pos,
                "part_no": str(part_no).strip() if part_no is not None and str(part_no).strip() != "" else None,
                "qty": qty,
                "designation": str(designation).strip() if designation is not None and str(designation).strip() != "" else None,
            }
        )
    return [row for row in rows if row.get("pos") is not None or row.get("part_no") or row.get("designation")]


def _extract_parts_with_page(csv_path: str, column_map: dict[str, str]) -> list[dict]:
    with open(csv_path, "rb") as f:
        raw_bytes = f.read()
    try:
        raw_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode("latin1")

    df = pd.read_csv(io.StringIO(raw_text), sep=None, engine="python")
    df.columns = [str(c).strip().lower() for c in df.columns]
    normalized_cols = {_normalize_header(c): c for c in df.columns}

    def col_by_candidates(candidates):
        for cand in candidates:
            key = _normalize_header(cand or "")
            if key in normalized_cols:
                return df[normalized_cols[key]]
        for cand in candidates:
            key = _normalize_header(cand or "")
            for norm_key, actual in normalized_cols.items():
                if key and key in norm_key:
                    return df[actual]
        return None

    col_pos = col_by_candidates([column_map.get("pos", "pos"), "pos", "position", "item", "item_no"])
    col_part = col_by_candidates([
        column_map.get("part_no", "part_no"),
        "part_no",
        "partno",
        "part number",
        "part_number",
        "system_part_number",
        "oem_part_no",
        "oem",
        "part",
    ])
    col_qty = col_by_candidates([column_map.get("qty", "qty"), "qty", "quantity", "qty_required"])
    col_designation = col_by_candidates([
        column_map.get("designation", "designation"),
        "designation",
        "description",
        "desc",
        "name",
    ])
    col_page = col_by_candidates(["page", "page_number", "page_no", "page_index"])

    rows = []
    for idx in range(len(df)):
        pos = _coerce_int(col_pos.iloc[idx]) if col_pos is not None else None
        part_no = str(col_part.iloc[idx]).strip() if col_part is not None else ""
        qty = _coerce_int(col_qty.iloc[idx]) if col_qty is not None else None
        designation = str(col_designation.iloc[idx]).strip() if col_designation is not None else ""
        page_val = _coerce_int(col_page.iloc[idx]) if col_page is not None else None
        if not (pos is not None or part_no or designation):
            continue
        rows.append(
            {
                "pos": pos,
                "part_no": part_no,
                "qty": qty,
                "designation": designation,
                "page": page_val,
            }
        )
    return rows


@illustrations_bp.route("/admin/templates/<int:template_id>/sections/<int:section_id>/illustrations", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def illustration_wizard(template_id, section_id):
    template = _get_or_404(Template, template_id)

    items = (
        TemplateItem.query.filter_by(template_id=template.id)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )
    section_map = _ensure_template_sections(template, items)
    section = _get_or_404(TemplateSection, section_id)
    if section.template_id != template.id:
        abort(404)

    step = (request.args.get("step") or "0").strip()
    page_id = request.args.get("page_id")
    page = None
    if page_id:
        page = _get_illustration_page_for_template(page_id, template)
    if not page:
        link = (
            TemplateSectionIllustrationLink.query
            .filter_by(template_section_id=section.id)
            .order_by(TemplateSectionIllustrationLink.display_order, TemplateSectionIllustrationLink.id)
            .first()
        )
        if link and link.page:
            page = link.page
    if not page:
        legacy_rel_path = _find_legacy_section_image(template, section.name)
        if legacy_rel_path:
            page = IllustrationPage(
                title=section.name,
                image_path=legacy_rel_path,
                status="draft",
                created_by_id=current_user().id if current_user() else None,
            )
            db.session.add(page)
            db.session.flush()
            link = TemplateSectionIllustrationLink(
                template_section_id=section.id,
                illustration_page_id=page.id,
                display_order=0,
            )
            db.session.add(link)
            section_items = (
                TemplateItem.query
                .filter_by(template_id=template.id, section=section.name)
                .order_by(TemplateItem.pos, TemplateItem.id)
                .all()
            )
            for item in section_items:
                if item.pos is None and not item.part_no and not item.name:
                    continue
                db.session.add(
                    IllustrationPartRow(
                        illustration_page_id=page.id,
                        pos=item.pos or 0,
                        part_no=item.part_no,
                        qty=item.qty or 1,
                        designation=item.name,
                    )
                )
            log_event(
                action="illustration_legacy_bootstrap",
                message=f"Legacy illustration linked for section {section.name}",
                user=current_user(),
            )
            db.session.commit()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        action_page_id = request.form.get("page_id") or page_id
        if action_page_id and not page:
            page = _get_illustration_page_for_template(action_page_id, template)

        if action == "create_page":
            uploaded = request.files.get("illustration_file")
            if not uploaded or uploaded.filename == "":
                flash("Select an image file to upload.", "danger")
                return redirect(request.url)
            try:
                rel_path = save_uploaded_file(
                    uploaded,
                    subdir=f"illustrations/{template.id}",
                    allowed_exts=ALLOWED_IMAGE_EXTENSIONS,
                    allowed_mimetypes=ALLOWED_IMAGE_MIME_TYPES,
                    require_image=True,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(request.url)

            title = (request.form.get("title") or "").strip() or None
            try:
                natural_w = int(request.form.get("natural_w") or 0) or None
            except ValueError:
                natural_w = None
            try:
                natural_h = int(request.form.get("natural_h") or 0) or None
            except ValueError:
                natural_h = None

            page = IllustrationPage(
                title=title,
                image_path=rel_path or "",
                natural_w=natural_w,
                natural_h=natural_h,
                status="draft",
                created_by_id=current_user().id if current_user() else None,
            )
            db.session.add(page)
            db.session.flush()
            link = TemplateSectionIllustrationLink(
                template_section_id=section.id,
                illustration_page_id=page.id,
                display_order=0,
            )
            db.session.add(link)
            log_event(
                action="illustration_created",
                message=f"Illustration page created for section {section.name}",
                user=current_user(),
            )
            db.session.commit()
            flash("Illustration page created.", "success")
            return redirect(url_for("illustrations_bp.illustration_wizard", template_id=template.id, section_id=section.id, step="1", page_id=page.id))

        if action == "delete_page" and page:
            IllustrationPartRow.query.filter_by(illustration_page_id=page.id).delete()
            IllustrationPosLabel.query.filter_by(illustration_page_id=page.id).delete()
            IllustrationHotspot.query.filter_by(illustration_page_id=page.id).delete()
            TemplateSectionIllustrationLink.query.filter_by(illustration_page_id=page.id).delete()
            db.session.delete(page)
            log_event(
                action="illustration_deleted",
                message=f"Illustration page deleted for section {section.name}",
                user=current_user(),
            )
            db.session.commit()
            flash("Illustration page deleted.", "success")
            return redirect(url_for("illustrations_bp.illustration_wizard", template_id=template.id, section_id=section.id, step="0"))

        if action == "import_pdf":
            uploaded = request.files.get("pdf_file")
            if not uploaded or uploaded.filename == "":
                flash("Select a PDF file to import.", "danger")
                return redirect(request.url)
            try:
                validate_upload(
                    uploaded,
                    allowed_exts=ALLOWED_PDF_EXTENSIONS,
                    allowed_mimetypes=ALLOWED_PDF_MIME_TYPES,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(request.url)

            try:
                import fitz  # type: ignore
            except Exception:
                flash("PDF import requires PyMuPDF (pymupdf). Install dependencies and retry.", "danger")
                return redirect(request.url)

            run_extract, _, extractor_err = _get_pdf_extractor()
            if not run_extract:
                flash(
                    f"PDF extractor not available. Run scripts/check_pdf_extractor.sh and fix any errors. ({extractor_err})",
                    "danger",
                )
                return redirect(request.url)

            profile = (request.form.get("pdf_profile") or "auto").strip() or "auto"

            with tempfile.TemporaryDirectory(prefix="pdf_extract_") as tmp_dir:
                pdf_name = secure_filename(uploaded.filename) or "upload.pdf"
                pdf_path = os.path.join(tmp_dir, pdf_name)
                uploaded.save(pdf_path)

                out_dir = os.path.join(tmp_dir, "out")
                os.makedirs(out_dir, exist_ok=True)
                try:
                    run_extract(pdf_path, out_dir, profile, debug=False)
                except Exception as exc:
                    flash(f"PDF extractor failed: {exc}", "danger")
                    return redirect(request.url)

                parts_csv_path = os.path.join(out_dir, "parts.csv")
                if not os.path.exists(parts_csv_path):
                    flash("PDF extractor did not produce parts.csv.", "danger")
                    return redirect(request.url)

                try:
                    extracted_rows = _extract_parts_with_page(
                        parts_csv_path,
                        {"pos": "pos", "part_no": "part_no", "qty": "qty", "designation": "designation"},
                    )
                except Exception as exc:
                    flash(f"Unable to read parts.csv: {exc}", "danger")
                    return redirect(request.url)

                rows_by_page = {}
                for row in extracted_rows:
                    page_no = row.get("page") or 1
                    rows_by_page.setdefault(page_no, []).append(row)

                try:
                    doc = fitz.open(pdf_path)
                except Exception as exc:
                    flash(f"Unable to read PDF: {exc}", "danger")
                    return redirect(request.url)

                max_pages = 200
                if doc.page_count > max_pages:
                    flash(f"PDF has {doc.page_count} pages. Limit is {max_pages}.", "danger")
                    return redirect(request.url)

                base_subdir = f"illustrations/{template.id}/pdf_{int(time.time())}"
                base_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], base_subdir)
                os.makedirs(base_dir, exist_ok=True)
                existing_order = (
                    db.session.query(db.func.max(TemplateSectionIllustrationLink.display_order))
                    .filter_by(template_section_id=section.id)
                    .scalar()
                    or 0
                )

                created_pages = 0
                pages_with_rows = 0
                for page_index in range(doc.page_count):
                    pdf_page = doc.load_page(page_index)
                    filename = f"page_{page_index + 1:03d}.png"
                    abs_path = os.path.join(base_dir, filename)
                    image, natural_w, natural_h = render_cropped_page(pdf_page)
                    image.save(abs_path)
                    rel_path = os.path.relpath(abs_path, current_app.config["UPLOAD_FOLDER"])

                    rows = rows_by_page.get(page_index + 1, [])
                    rows_with_pos = [row for row in rows if row.get("pos") is not None]
                    errors = _validate_parts(rows_with_pos) if rows_with_pos else []
                    errors = [err for err in errors if not err.startswith("Duplicate POS")]

                    page_title = f"{os.path.splitext(uploaded.filename)[0]} p{page_index + 1}"
                    page = IllustrationPage(
                        title=page_title,
                        image_path=rel_path,
                        natural_w=natural_w,
                        natural_h=natural_h,
                        status="draft",
                        created_by_id=current_user().id if current_user() else None,
                    )
                    db.session.add(page)
                    db.session.flush()

                    link = TemplateSectionIllustrationLink(
                        template_section_id=section.id,
                        illustration_page_id=page.id,
                        display_order=existing_order + created_pages + 1,
                    )
                    db.session.add(link)

                    if rows_with_pos and not errors:
                        pos_counter = 1
                        for row in rows_with_pos:
                            pos_value = row.get("pos") or pos_counter
                            db.session.add(
                                IllustrationPartRow(
                                    illustration_page_id=page.id,
                                    pos=pos_value,
                                    part_no=row.get("part_no") or None,
                                    qty=row.get("qty") or 1,
                                    designation=row.get("designation") or None,
                                )
                            )
                            pos_counter = max(pos_counter, pos_value) + 1
                        pages_with_rows += 1
                    created_pages += 1

                db.session.commit()
                flash(
                    f"Imported {created_pages} pages from PDF. {pages_with_rows} pages had parts rows.",
                    "success",
                )
                return redirect(
                    url_for(
                        "illustrations_bp.illustration_wizard",
                        template_id=template.id,
                        section_id=section.id,
                        step="0",
                    )
                )

        if action == "import_parts" and page:
            uploaded = request.files.get("parts_file")
            pasted = (request.form.get("parts_paste") or "").strip()
            column_map = {
                "pos": request.form.get("col_pos") or "pos",
                "part_no": request.form.get("col_part_no") or "part_no",
                "qty": request.form.get("col_qty") or "qty",
                "designation": request.form.get("col_designation") or "name",
            }
            rows = []
            if uploaded and uploaded.filename:
                try:
                    rows = _load_parts_from_upload(uploaded, column_map)
                except ValueError as exc:
                    flash(str(exc), "danger")
                    return redirect(request.url)
            elif pasted:
                parsed_rows, header = _parse_parts_from_text(pasted)
                if parsed_rows:
                    if header and "pos" in header:
                        rows = _extract_columns_by_header(parsed_rows[1:], header, column_map)
                    if not rows:
                        rows = _extract_columns_with_shift(parsed_rows)
            if not rows:
                flash("No parts rows detected.", "danger")
                return redirect(request.url)

            rows = [row for row in rows if row.get("pos") is not None or row.get("part_no") or row.get("designation")]
            rows_with_pos = [row for row in rows if row.get("pos") is not None]
            if not rows_with_pos:
                flash("No valid POS values found. Check the POS column mapping.", "danger")
                return redirect(request.url)

            errors = _validate_parts(rows_with_pos)
            if errors:
                flash(" ".join(sorted(set(errors))), "danger")
                return redirect(request.url)

            if not rows:
                flash("No valid POS values found. Check the POS column mapping.", "danger")
                return redirect(request.url)

            IllustrationPartRow.query.filter_by(illustration_page_id=page.id).delete()
            db.session.flush()
            for row in rows:
                if row.get("pos") is None:
                    continue
                db.session.add(
                    IllustrationPartRow(
                        illustration_page_id=page.id,
                        pos=row["pos"],
                        part_no=row.get("part_no"),
                        qty=row.get("qty") or 1,
                        designation=row.get("designation"),
                    )
                )
            log_event(
                action="illustration_parts_imported",
                message=f"Imported {len(rows)} parts rows for illustration {page.id}",
                user=current_user(),
            )
            db.session.commit()
            flash("Parts list imported.", "success")
            return redirect(request.url)

        if action == "update_rows" and page:
            rows = IllustrationPartRow.query.filter_by(illustration_page_id=page.id).order_by(IllustrationPartRow.pos).all()
            updates = []
            invalid_rows = []
            for row in rows:
                pos_raw = request.form.get(f"pos_{row.id}")
                part_no = (request.form.get(f"part_no_{row.id}") or "").strip() or None
                designation = (request.form.get(f"designation_{row.id}") or "").strip() or None
                qty_raw = request.form.get(f"qty_{row.id}")
                try:
                    pos_val = int(pos_raw) if pos_raw else None
                except ValueError:
                    pos_val = None
                try:
                    qty_val = int(qty_raw) if qty_raw else 1
                except ValueError:
                    qty_val = 1
                if pos_val is None and (part_no or designation):
                    invalid_rows.append(row.id)
                updates.append((row, pos_val, part_no, qty_val, designation))

            errors = _validate_parts([{"pos": p} for _, p, _, _, _ in updates])
            if errors:
                flash(" ".join(sorted(set(errors))), "danger")
                return redirect(request.url)
            if invalid_rows:
                flash("POS must be an integer for all edited rows.", "danger")
                return redirect(request.url)

            for row, pos_val, part_no, qty_val, designation in updates:
                row.pos = pos_val
                row.part_no = part_no
                row.qty = qty_val
                row.designation = designation
            db.session.commit()
            flash("Parts list updated.", "success")
            return redirect(request.url)

        if action == "save_display" and page:
            display_config = {
                "sort": request.form.get("sort_mode") or "pos",
                "filters": request.form.getlist("filters") or [],
                "grouping": request.form.get("grouping") or "none",
                "bulk_apply": bool(request.form.get("bulk_apply")),
                "next_undecided": bool(request.form.get("next_undecided")),
            }
            page.display_config_json = display_config
            db.session.commit()
            flash("Display options saved.", "success")
            return redirect(request.url)

        if action == "publish" and page:
            page.status = "published"
            page.published_at = datetime.now(timezone.utc)
            db.session.commit()
            log_event(
                action="illustration_published",
                message=f"Illustration page {page.id} published",
                user=current_user(),
            )
            flash("Illustration published.", "success")
            return redirect(request.url)

        if action == "archive" and page:
            page.status = "archived"
            db.session.commit()
            flash("Illustration archived.", "success")
            return redirect(url_for("illustrations_bp.illustration_wizard", template_id=template.id, section_id=section.id, step="0"))

        if action == "reorder":
            order_map = {}
            for field, value in request.form.items():
                if not field.startswith("order_"):
                    continue
                try:
                    pid = int(field.replace("order_", ""))
                    order_map[pid] = int(value)
                except (TypeError, ValueError):
                    continue
            if order_map:
                links = TemplateSectionIllustrationLink.query.filter_by(template_section_id=section.id).all()
                for link in links:
                    if link.illustration_page_id in order_map:
                        link.display_order = order_map[link.illustration_page_id]
                db.session.commit()
                flash("Order updated.", "success")
            return redirect(url_for("illustrations_bp.illustration_wizard", template_id=template.id, section_id=section.id, step="0"))

    pages = (
        IllustrationPage.query
        .join(TemplateSectionIllustrationLink)
        .filter(TemplateSectionIllustrationLink.template_section_id == section.id)
        .order_by(TemplateSectionIllustrationLink.display_order, IllustrationPage.id)
        .all()
    )
    if step != "0" and page is None and pages:
        return redirect(
            url_for(
                "illustrations_bp.illustration_wizard",
                template_id=template.id,
                section_id=section.id,
                step=step,
                page_id=pages[0].id,
            )
        )

    page_stats = []
    for p in pages:
        rows = IllustrationPartRow.query.filter_by(illustration_page_id=p.id).all()
        labels = IllustrationPosLabel.query.filter_by(illustration_page_id=p.id).all()
        pos_set = {r.pos for r in rows}
        label_set = {l.pos for l in labels}
        unmapped = len(pos_set - label_set)
        page_stats.append({
            "page": p,
            "rows": len(rows),
            "labels": len(labels),
            "unmapped": unmapped,
        })

    parts_rows = []
    labels = []
    hotspots = []
    hotspots_payload = []
    if page:
        template_rows = (
            TemplateItem.query
            .filter_by(template_id=template.id, section=section.name)
            .order_by(TemplateItem.pos, TemplateItem.id)
            .all()
        )
        if template_rows:
            IllustrationPartRow.query.filter_by(illustration_page_id=page.id).delete()
            pos_counter = 1
            for item in template_rows:
                pos_value = item.pos or pos_counter
                db.session.add(
                    IllustrationPartRow(
                        illustration_page_id=page.id,
                        pos=pos_value,
                        part_no=item.part_no or "",
                        qty=item.qty or 1,
                        designation=item.name or "",
                    )
                )
                pos_counter = max(pos_counter, (pos_value or pos_counter)) + 1
            db.session.commit()
        parts_rows = IllustrationPartRow.query.filter_by(illustration_page_id=page.id).order_by(IllustrationPartRow.pos).all()
        labels = IllustrationPosLabel.query.filter_by(illustration_page_id=page.id).all()
        hotspots = IllustrationHotspot.query.filter_by(illustration_page_id=page.id).all()
        hotspots_payload = [
            {"pos": hs.pos, "shape_json": hs.shape_json}
            for hs in hotspots
        ]

    pdf_profiles, pdf_profiles_error = _list_pdf_profiles()

    return render_template(
        "illustration_wizard.html",
        template=template,
        section=section,
        section_map=section_map,
        step=step,
        page=page,
        pages=pages,
        page_stats=page_stats,
        parts_rows=parts_rows,
        labels=labels,
        hotspots=hotspots,
        hotspots_payload=hotspots_payload,
        pdf_profiles=pdf_profiles,
        pdf_profiles_error=pdf_profiles_error,
    )


@illustrations_bp.route("/api/template_sections/<int:section_id>/illustrations", methods=["GET"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def api_section_illustrations(section_id):
    section = _get_or_404(TemplateSection, section_id)
    links = (
        TemplateSectionIllustrationLink.query
        .filter_by(template_section_id=section.id)
        .order_by(TemplateSectionIllustrationLink.display_order)
        .all()
    )
    pages = []
    for link in links:
        page = link.page
        if not page:
            continue
        pages.append(
            {
                "id": page.id,
                "title": page.title,
                "status": page.status,
                "image_path": page.image_path,
                "natural_w": page.natural_w,
                "natural_h": page.natural_h,
            }
        )
    return jsonify({"section": section.name, "pages": pages})


@illustrations_bp.route("/api/illustrations", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_create_illustration():
    uploaded = request.files.get("illustration_file")
    if not uploaded or uploaded.filename == "":
        return jsonify({"error": "Missing illustration_file."}), 400
    try:
        rel_path = save_uploaded_file(
            uploaded,
            subdir="illustrations",
            allowed_exts=ALLOWED_IMAGE_EXTENSIONS,
            allowed_mimetypes=ALLOWED_IMAGE_MIME_TYPES,
            require_image=True,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    title = (request.form.get("title") or "").strip() or None
    page = IllustrationPage(
        title=title,
        image_path=rel_path or "",
        status="draft",
        created_by_id=current_user().id if current_user() else None,
    )
    db.session.add(page)
    db.session.commit()
    return jsonify({"id": page.id, "status": page.status}), 201


@illustrations_bp.route("/api/illustrations/<int:page_id>", methods=["PUT"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_update_illustration(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    payload = request.get_json(silent=True) or {}
    if "title" in payload:
        page.title = (payload.get("title") or "").strip() or None
    if "status" in payload:
        page.status = payload.get("status") or page.status
    if "display_config_json" in payload:
        page.display_config_json = payload.get("display_config_json")
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/illustrations/<int:page_id>/parts/import", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_import_parts(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "Missing rows list."}), 400
    errors = _validate_parts(rows)
    if errors:
        return jsonify({"error": " ".join(sorted(set(errors)))}), 400

    IllustrationPartRow.query.filter_by(illustration_page_id=page.id).delete()
    db.session.flush()
    for row in rows:
        db.session.add(
            IllustrationPartRow(
                illustration_page_id=page.id,
                pos=int(row.get("pos")),
                part_no=row.get("part_no"),
                qty=int(row.get("qty") or 1),
                designation=row.get("designation"),
            )
        )
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/illustrations/<int:page_id>/parts", methods=["PUT"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_update_parts(page_id):
    return api_import_parts(page_id)


@illustrations_bp.route("/api/template_sections/<int:section_id>/illustrations/link", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_link_illustration(section_id):
    section = _get_or_404(TemplateSection, section_id)
    payload = request.get_json(silent=True) or {}
    page_id = payload.get("page_id")
    try:
        page_id = int(page_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid page_id."}), 400
    page = _get_or_404(IllustrationPage, page_id)
    link = TemplateSectionIllustrationLink(
        template_section_id=section.id,
        illustration_page_id=page.id,
        display_order=payload.get("display_order") or 0,
    )
    db.session.add(link)
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/template_sections/<int:section_id>/illustrations/reorder", methods=["PUT"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_reorder_illustrations(section_id):
    section = _get_or_404(TemplateSection, section_id)
    payload = request.get_json(silent=True) or {}
    order = payload.get("order") or []
    if not isinstance(order, list):
        return jsonify({"error": "Order must be a list."}), 400
    order_map = {int(entry.get("page_id")): int(entry.get("display_order") or 0) for entry in order if entry.get("page_id")}
    links = TemplateSectionIllustrationLink.query.filter_by(template_section_id=section.id).all()
    for link in links:
        if link.illustration_page_id in order_map:
            link.display_order = order_map[link.illustration_page_id]
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/illustrations/<int:page_id>/publish", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_publish_illustration(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    page.status = "published"
    page.published_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/illustrations/<int:page_id>/pos_labels", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_set_pos_label(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    payload = request.get_json(silent=True) or {}
    try:
        pos_val = int(payload.get("pos"))
    except (TypeError, ValueError):
        return jsonify({"error": "POS must be an integer."}), 400
    try:
        x_norm = float(payload.get("x_norm"))
        y_norm = float(payload.get("y_norm"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid coordinates."}), 400
    if not (0 <= x_norm <= 1 and 0 <= y_norm <= 1):
        return jsonify({"error": "Coordinates must be normalized 0..1."}), 400

    label_id = payload.get("label_id")
    label = None
    if label_id:
        try:
            label = IllustrationPosLabel.query.filter_by(
                id=int(label_id), illustration_page_id=page.id
            ).first()
        except (TypeError, ValueError):
            label = None
    if label:
        label.x_norm = x_norm
        label.y_norm = y_norm
        label.pos = pos_val
    else:
        label = IllustrationPosLabel(
            illustration_page_id=page.id,
            pos=pos_val,
            x_norm=x_norm,
            y_norm=y_norm,
        )
        db.session.add(label)
    db.session.commit()
    return jsonify({
        "status": "ok",
        "label_id": label.id,
        "pos": pos_val,
        "x_norm": x_norm,
        "y_norm": y_norm,
    })


@illustrations_bp.route("/api/illustrations/<int:page_id>/pos_labels/<int:label_id>", methods=["DELETE"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_delete_pos_label(page_id, label_id):
    page = _get_or_404(IllustrationPage, page_id)
    label = IllustrationPosLabel.query.filter_by(id=label_id, illustration_page_id=page.id).first()
    if not label:
        return jsonify({"error": "Label not found."}), 404
    db.session.delete(label)
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/illustrations/<int:page_id>/hotspots", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_create_hotspot(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    payload = request.get_json(silent=True) or {}
    try:
        pos_val = int(payload.get("pos"))
    except (TypeError, ValueError):
        return jsonify({"error": "POS must be an integer."}), 400
    shape = payload.get("shape_json")
    if not isinstance(shape, list) or not shape:
        return jsonify({"error": "shape_json must be a list of points."}), 400
    for pt in shape:
        try:
            x = float(pt[0])
            y = float(pt[1])
        except (TypeError, ValueError, IndexError):
            return jsonify({"error": "Invalid point in shape_json."}), 400
        if not (0 <= x <= 1 and 0 <= y <= 1):
            return jsonify({"error": "Points must be normalized 0..1."}), 400

    existing = IllustrationHotspot.query.filter_by(illustration_page_id=page.id, pos=pos_val).first()
    if existing:
        existing.shape_json = shape
        db.session.commit()
        return jsonify({"status": "ok", "id": existing.id})

    hotspot = IllustrationHotspot(
        illustration_page_id=page.id,
        pos=pos_val,
        shape_json=shape,
    )
    db.session.add(hotspot)
    db.session.commit()
    return jsonify({"status": "ok", "id": hotspot.id}), 201


@illustrations_bp.route("/api/illustrations/<int:page_id>/hotspots", methods=["PUT"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_replace_hotspots(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    payload = request.get_json(silent=True) or {}
    hotspots = payload.get("hotspots") or []
    if not isinstance(hotspots, list):
        return jsonify({"error": "hotspots must be a list."}), 400

    IllustrationHotspot.query.filter_by(illustration_page_id=page.id).delete()
    db.session.flush()
    for entry in hotspots:
        try:
            pos_val = int(entry.get("pos"))
        except (TypeError, ValueError):
            return jsonify({"error": "POS must be an integer."}), 400
        shape = entry.get("shape_json")
        if not isinstance(shape, list) or not shape:
            return jsonify({"error": "shape_json must be a list of points."}), 400
        for pt in shape:
            try:
                x = float(pt[0])
                y = float(pt[1])
            except (TypeError, ValueError, IndexError):
                return jsonify({"error": "Invalid point in shape_json."}), 400
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return jsonify({"error": "Points must be normalized 0..1."}), 400
        db.session.add(
            IllustrationHotspot(
                illustration_page_id=page.id,
                pos=pos_val,
                shape_json=shape,
            )
        )
    db.session.commit()
    return jsonify({"status": "ok"})


@illustrations_bp.route("/api/illustrations/<int:page_id>/hotspots", methods=["DELETE"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def api_delete_hotspot(page_id):
    page = _get_or_404(IllustrationPage, page_id)
    hotspot_id = request.args.get("hotspot_id")
    if not hotspot_id:
        return jsonify({"error": "hotspot_id is required."}), 400
    try:
        hotspot_id = int(hotspot_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid hotspot_id."}), 400
    hotspot = IllustrationHotspot.query.filter_by(id=hotspot_id, illustration_page_id=page.id).first()
    if not hotspot:
        return jsonify({"error": "Hotspot not found."}), 404
    db.session.delete(hotspot)
    db.session.commit()
    return jsonify({"status": "ok"})
