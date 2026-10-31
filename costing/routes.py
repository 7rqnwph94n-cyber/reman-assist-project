import os
import tempfile
import io
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    request,
    send_file,
    send_from_directory,
    url_for,
    render_template,
    Response,
    jsonify,
    current_app,
)

from auth_utils import login_required, roles_required, require_job_access, current_user, get_org_filter, get_scoped_or_404
from models import (
    db,
    Job,
    Template,
    CostingTemplateProfile,
    CostingTemplateLine,
    LineClassEnum,
    ProcurementStatusEnum,
    MatchStatusEnum,
    PartRequirement,
    CostingSheet,
    JobCostingUpload,
    CostingStageEnum,
    CostingLine,
)
from services.costing import (
    ensure_costing_sheet,
    ensure_costing_sheet_from_template,
    create_costing_lines_from_template,
    bind_costing_lines_to_bom,
    export_costing_sheet_xlsx,
    enrich_bom_from_catalogue,
    create_costing_lines_from_bom,
)
from services.job_services import log_event
from utils.localization import t
from utils.pagination import parse_int
from file_utils import (
    save_uploaded_file,
    validate_upload,
    ALLOWED_COSTING_TEMPLATE_EXTENSIONS,
    ALLOWED_COSTING_TEMPLATE_MIME_TYPES,
)

costing_bp = Blueprint("costing", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)


def _find_active_profile(template_id: int) -> CostingTemplateProfile | None:
    return (
        CostingTemplateProfile.query.filter_by(engine_template_id=template_id, is_active=True)
        .order_by(CostingTemplateProfile.version.desc())
        .first()
    )


def _latest_job_upload(job_id: int) -> JobCostingUpload | None:
    return (
        JobCostingUpload.query.filter_by(job_id=job_id)
        .order_by(JobCostingUpload.version.desc(), JobCostingUpload.id.desc())
        .first()
    )


def _resolve_upload_path(rel_path: str | None) -> str:
    if not rel_path:
        return ""
    upload_folder = current_app.config.get("UPLOAD_FOLDER") or ""
    if os.path.isabs(rel_path):
        full = rel_path
    else:
        full = os.path.join(upload_folder, rel_path)
    # Prevent path traversal: resolved path must stay within UPLOAD_FOLDER
    if upload_folder and not os.path.realpath(full).startswith(os.path.realpath(upload_folder)):
        current_app.logger.warning(f"Path traversal blocked: {rel_path}")
        return ""
    return full


def _build_costing_csv_response(job: Job, sheet: CostingSheet, profile: CostingTemplateProfile | None, filename: str) -> Response:
    col_order = []
    header_names = {}
    if profile and profile.required_columns_json:
        for logical, header in profile.required_columns_json.items():
            col_order.append(logical)
            header_names[logical] = header
    else:
        col_order = [
            "line_no",
            "group_no",
            "figure",
            "item_no",
            "oem_part_no",
            "part_description",
            "qty_required",
            "notes",
            "line_class",
            "rbb_value",
            "menu_sell_price_unit",
            "intended_supplier",
            "system_part_number",
            "qty_on_stock",
            "qty_on_order",
            "latest_supplier",
            "latest_cost",
            "price_cost",
            "is_kit",
            "is_menu",
            "is_consumable",
            "unit_cost_confirmed",
            "line_cost",
            "po_number",
            "procurement_status",
            "emergent_line_cost",
            "emergent_qty_required",
        ]
        header_names = {
            "line_no": "Line No",
            "group_no": "Group No",
            "figure": "Figure",
            "item_no": "Item No",
            "oem_part_no": "OEM PART No",
            "part_description": "Part Description",
            "qty_required": "Qty Required",
            "notes": "Notes",
            "line_class": "100% Replacement / Class",
            "rbb_value": "RBB value",
            "menu_sell_price_unit": "Menu Item Sell Price/Unit",
            "intended_supplier": "Intended Supplier",
            "system_part_number": "System Part Number",
            "qty_on_stock": "Qty on Stock",
            "qty_on_order": "Qty On Order",
            "latest_supplier": "Latest Supplier",
            "latest_cost": "Latest Cost",
            "price_cost": "Price/Cost",
            "is_kit": "Kit",
            "is_menu": "Menu Item",
            "is_consumable": "Consumable",
            "unit_cost_confirmed": "Cost/Unit",
            "line_cost": "Line Cost",
            "po_number": "PO Number",
            "procurement_status": "Status",
            "emergent_line_cost": "EMERGENT Line Cost",
            "emergent_qty_required": "EMERGENT Qty Required",
        }

    output = io.StringIO()
    writer = csv.writer(output)
    headers = [header_names.get(col, col) for col in col_order]
    writer.writerow(headers)

    for line in sheet.lines:
        row = []
        for col in col_order:
            val = getattr(line, col, None)
            if col in {"procurement_status", "line_class"} and val is not None and hasattr(val, "value"):
                val = val.value
            if col in {"is_menu", "is_kit", "is_consumable"}:
                val = 1 if val else 0
            row.append(val if val is not None else "")
        writer.writerow(row)

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _parse_costing_upload(file_path: str, sheet_name: str | None = None) -> list[dict]:
    if not file_path:
        return []
    if file_path.lower().endswith(".csv"):
        df = pd.read_csv(file_path)
    else:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
    df.columns = [str(c).strip().lower() for c in df.columns]

    def col(*names):
        for n in names:
            key = n.lower().strip()
            if key in df.columns:
                return df[key]
        for n in names:
            key = n.lower().strip()
            for colname in df.columns:
                if key in colname:
                    return df[colname]
        return None

    col_line = col("line_no", "line no")
    col_group = col("group_no", "group no")
    col_figure = col("figure")
    col_item = col("item_no", "item no")
    col_part = col("system_part_number", "part_no", "part no", "part number", "partnumber", "part")
    col_oem = col("oem_part_no", "oem part no", "oem part number", "oem")
    col_desc = col("description", "part_description", "part name", "item description")
    col_supplier = col("supplier", "intended supplier", "latest supplier")
    col_cost = col("latest_cost", "cost", "unit cost", "price")
    col_menu = col("menu_sell_price_unit", "menu price", "sell price")
    col_qty = col("qty_required", "qty", "quantity")

    rows = []
    for idx in range(len(df)):
        def _val(series):
            if series is None or pd.isna(series.iloc[idx]):
                return None
            return series.iloc[idx]

        def _parse_float(value):
            try:
                return Decimal(str(value)) if value is not None else None
            except (TypeError, ValueError, InvalidOperation):
                return None

        part_no = _val(col_part)
        oem_no = _val(col_oem)
        desc = _val(col_desc)
        if not (part_no or oem_no or desc):
            continue

        rows.append(
            {
                "line_no": parse_int(_val(col_line)) or (idx + 1),
                "group_no": _val(col_group),
                "figure": _val(col_figure),
                "item_no": _val(col_item),
                "system_part_number": str(part_no).strip() if part_no is not None else None,
                "oem_part_no": str(oem_no).strip() if oem_no is not None else None,
                "part_description": str(desc).strip() if desc is not None else None,
                "intended_supplier": str(_val(col_supplier)).strip() if _val(col_supplier) is not None else None,
                "latest_supplier": str(_val(col_supplier)).strip() if _val(col_supplier) is not None else None,
                "latest_cost": _parse_float(_val(col_cost)),
                "menu_sell_price_unit": _parse_float(_val(col_menu)),
                "qty_required": parse_int(_val(col_qty)) or 0,
            }
        )
    return rows


def _apply_costing_upload(job: Job, upload: JobCostingUpload, sheet_name: str | None = None) -> int:
    sheet = ensure_costing_sheet(job, upload=upload)
    CostingLine.query.filter_by(costing_sheet_id=sheet.id).delete()
    db.session.flush()

    rows = _parse_costing_upload(_resolve_upload_path(upload.file_path), sheet_name=sheet_name)
    created = 0
    for row in rows:
        line = CostingLine(
            sheet=sheet,
            line_no=row.get("line_no") or created + 1,
            group_no=row.get("group_no"),
            figure=row.get("figure"),
            item_no=row.get("item_no"),
            oem_part_no=row.get("oem_part_no"),
            system_part_number=row.get("system_part_number"),
            part_description=row.get("part_description"),
            line_class=row.get("line_class") or LineClassEnum.STANDARD,
            intended_supplier=row.get("intended_supplier"),
            latest_supplier=row.get("latest_supplier"),
            latest_cost=row.get("latest_cost"),
            menu_sell_price_unit=row.get("menu_sell_price_unit"),
            qty_required=row.get("qty_required") or 0,
            procurement_status=ProcurementStatusEnum.NOT_COSTED,
            match_status=MatchStatusEnum.UNMATCHED_SHEET,
        )
        db.session.add(line)
        created += 1

    sheet.job_costing_upload_id = upload.id
    sheet.transition_stage_to(CostingStageEnum.COSTING_IN_PROGRESS)
    upload.parsed_at = datetime.now(timezone.utc)
    db.session.commit()

    bind_costing_lines_to_bom(job)
    return created


@costing_bp.route("/jobs/<int:job_id>/costing", methods=["GET", "POST"])
@login_required
@roles_required("Admin", "Office")
def job_costing(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    profile = _find_active_profile(job.template_id) if job.template_id else None
    uploads = (
        JobCostingUpload.query.filter_by(job_id=job.id)
        .order_by(JobCostingUpload.version.desc(), JobCostingUpload.id.desc())
        .all()
    )
    active_upload = uploads[0] if uploads else None
    if active_upload:
        sheet = ensure_costing_sheet(job, upload=active_upload)
    elif profile:
        sheet = ensure_costing_sheet_from_template(job, profile)
    else:
        sheet = ensure_costing_sheet(job)

    if request.method == "POST":
        action = request.form.get("action") or "save"
        if profile and sheet.costing_template_profile_id != profile.id and action in {"rebind", "enrich"}:
            sheet.costing_template_profile_id = profile.id
            sheet.template_version_snapshot = profile.version
            db.session.commit()
        if action == "rebind":
            matched = bind_costing_lines_to_bom(job)
            flash(f"Rebound costing to {t('parts_list')} ({matched} matched).", "success")
        elif action == "enrich":
            if not profile:
                flash("No template catalogue available to enrich from.", "warning")
            else:
                stats = enrich_bom_from_catalogue(job, preserve_overrides=True)
                flash(
                    f"Enriched {stats.get('enriched',0)} line(s); {stats.get('missing',0)} missing catalogue data.",
                    "success",
                )
        else:
            for line in sheet.lines:
                line.intended_supplier = (request.form.get(f"supplier_{line.id}") or "").strip() or None
                line.po_number = (request.form.get(f"po_{line.id}") or "").strip() or None
                line.notes = (request.form.get(f"notes_{line.id}") or "").strip() or None
                try:
                    line.qty_required = int(request.form.get(f"qty_{line.id}") or line.qty_required or 0)
                except ValueError:
                    pass
                try:
                    raw_cost = request.form.get(f"unit_cost_{line.id}")
                    if raw_cost and raw_cost.strip():
                        line.unit_cost_confirmed = Decimal(raw_cost.strip())
                except (InvalidOperation, ValueError):
                    pass
                status_val = request.form.get(f"proc_status_{line.id}")
                if status_val:
                    try:
                        line.procurement_status = ProcurementStatusEnum(status_val)
                    except ValueError:
                        pass
            db.session.commit()
            flash("Costing sheet updated.", "success")

        return redirect(url_for("costing.job_costing", job_id=job.id))

    lines = sheet.lines
    unmatched = [l for l in lines if l.match_status != MatchStatusEnum.MATCHED]
    return render_template(
        "costing_sheet.html",
        job=job,
        sheet=sheet,
        lines=lines,
        unmatched=unmatched,
        ProcurementStatusEnum=ProcurementStatusEnum,
        MatchStatusEnum=MatchStatusEnum,
        uploads=uploads,
        active_upload=active_upload,
        enable_template_costing=current_app.config.get("ENABLE_TEMPLATE_COSTING", False),
    )


@costing_bp.route("/jobs/<int:job_id>/costing/upload", methods=["POST"])
@login_required
@roles_required("Admin", "Office")
def job_costing_upload(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)

    uploaded = request.files.get("costing_file")
    if not uploaded or uploaded.filename == "":
        flash("No costing file selected.", "danger")
        return redirect(url_for("costing.job_costing", job_id=job.id))

    try:
        validate_upload(
            uploaded,
            allowed_exts=ALLOWED_COSTING_TEMPLATE_EXTENSIONS,
            allowed_mimetypes=ALLOWED_COSTING_TEMPLATE_MIME_TYPES,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("costing.job_costing", job_id=job.id))

    sheet_name = (request.form.get("sheet_name") or "").strip() or None
    try:
        rel_path = save_uploaded_file(
            uploaded,
            subdir=f"costing_jobs/{job.id}",
            allowed_exts=ALLOWED_COSTING_TEMPLATE_EXTENSIONS,
            allowed_mimetypes=ALLOWED_COSTING_TEMPLATE_MIME_TYPES,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("costing.job_costing", job_id=job.id))

    latest_version = (
        db.session.query(db.func.max(JobCostingUpload.version))
        .filter_by(job_id=job.id)
        .scalar()
        or 0
    )
    upload = JobCostingUpload(
        job_id=job.id,
        version=latest_version + 1,
        file_path=rel_path or "",
        original_filename=uploaded.filename,
        sheet_name=sheet_name,
        uploaded_by_id=current_user().id if current_user() else None,
        uploaded_at=datetime.now(timezone.utc),
    )

    db.session.add(upload)
    db.session.flush()

    created = _apply_costing_upload(job, upload, sheet_name=sheet_name)
    log_event(
        action="job_costing_uploaded",
        message=f"Costing upload v{upload.version} applied ({created} lines).",
        job=job,
        user=current_user(),
    )
    db.session.commit()
    flash(f"Costing upload v{upload.version} applied ({created} line(s)).", "success")
    return redirect(url_for("costing.job_costing", job_id=job.id))


@costing_bp.route("/jobs/<int:job_id>/costing/use_upload", methods=["POST"])
@login_required
@roles_required("Admin", "Office")
def job_costing_use_upload(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    upload_id = request.form.get("upload_id")
    try:
        upload_id_int = int(upload_id) if upload_id else None
    except ValueError:
        upload_id_int = None
    if not upload_id_int:
        flash("Select a valid costing version.", "danger")
        return redirect(url_for("costing.job_costing", job_id=job.id))

    upload = JobCostingUpload.query.filter_by(id=upload_id_int, job_id=job.id).first()
    if not upload:
        flash("Selected costing version not found.", "danger")
        return redirect(url_for("costing.job_costing", job_id=job.id))

    created = _apply_costing_upload(job, upload, sheet_name=upload.sheet_name)
    log_event(
        action="job_costing_reapplied",
        message=f"Costing upload v{upload.version} re-applied ({created} lines).",
        job=job,
        user=current_user(),
    )
    db.session.commit()
    flash(f"Costing upload v{upload.version} re-applied ({created} line(s)).", "success")
    return redirect(url_for("costing.job_costing", job_id=job.id))


@costing_bp.route("/jobs/<int:job_id>/costing/uploads/<int:upload_id>")
@login_required
@roles_required("Admin", "Office")
def job_costing_download(job_id, upload_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    upload = JobCostingUpload.query.filter_by(id=upload_id, job_id=job.id).first()
    if not upload:
        abort(404)
    rel_path = upload.file_path
    full_path = _resolve_upload_path(rel_path)
    if not full_path or not os.path.exists(full_path):
        abort(404)
    return send_from_directory(
        current_app.config.get("UPLOAD_FOLDER") or "",
        rel_path,
        as_attachment=True,
        download_name=upload.original_filename or os.path.basename(rel_path),
    )


@costing_bp.route("/jobs/<int:job_id>/costing.json", methods=["GET"])
@login_required
@roles_required("Admin", "Office")
def costing_json(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    sheet = CostingSheet.query.filter_by(job_id=job.id).first()
    if not sheet:
        abort(404)
    payload = []
    for line in sheet.lines:
        payload.append(
            {
                "job_number": job.job_number,
                "line_no": line.line_no,
                "group_no": line.group_no,
                "figure": line.figure,
                "item_no": line.item_no,
                "system_part_number": line.system_part_number,
                "oem_part_no": line.oem_part_no,
                "part_description": line.part_description,
                "qty_required": line.qty_required,
                "qty_on_stock": line.qty_on_stock,
                "qty_on_order": line.qty_on_order,
                "intended_supplier": line.intended_supplier,
                "latest_supplier": line.latest_supplier,
                "latest_cost": line.latest_cost,
                "price_cost": line.price_cost,
                "menu_sell_price_unit": line.menu_sell_price_unit,
                "unit_cost_confirmed": line.unit_cost_confirmed,
                "line_cost": line.line_cost,
                "procurement_status": line.procurement_status.value if line.procurement_status else None,
                "po_number": line.po_number,
                "is_menu": line.is_menu,
                "is_kit": line.is_kit,
                "is_consumable": line.is_consumable,
                "line_class": line.line_class.value if line.line_class else None,
                "match_status": line.match_status.value if line.match_status else None,
                "emergent_qty_required": line.emergent_qty_required,
                "emergent_line_cost": line.emergent_line_cost,
                "emergent_reason": line.emergent_reason,
            }
        )
    return jsonify(payload)


@costing_bp.route("/jobs/<int:job_id>/costing/bind", methods=["POST"])
@login_required
@roles_required("Admin", "Office")
def bind_costing(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    if not job.template_id:
        flash("This job is not linked to an engine template, so costing cannot be generated.", "danger")
        return redirect(url_for("parts.job_parts", job_id=job.id))

    profile = _find_active_profile(job.template_id)
    if not profile:
        flash("No active costing template found for this engine template.", "warning")
        return redirect(url_for("parts.job_parts", job_id=job.id))

    sheet = ensure_costing_sheet_from_template(job, profile)
    if sheet.costing_template_profile_id != profile.id:
        sheet.costing_template_profile_id = profile.id
        sheet.template_version_snapshot = profile.version
        db.session.commit()

    # Seed lines from template catalogue if sheet is empty
    if not sheet.lines and profile.template_lines:
        rows = []
        for tl in profile.template_lines:
            rows.append(
                {
                    "line_no": tl.line_no,
                    "group_no": tl.group_no,
                    "figure": tl.figure,
                    "item_no": tl.item_no,
                    "oem_part_no": tl.oem_part_no,
                    "system_part_number": tl.system_part_number,
                    "part_description": tl.part_description,
                    "line_class": tl.default_class,
                    "is_menu": tl.is_menu,
                    "is_kit": tl.is_kit,
                    "is_consumable": tl.is_consumable,
                    "intended_supplier": tl.default_intended_supplier,
                    "latest_supplier": tl.default_latest_supplier,
                    "latest_cost": tl.default_latest_cost,
                    "menu_sell_price_unit": tl.default_menu_sell_price,
                    "qty_on_stock": tl.default_qty_on_stock,
                    "qty_on_order": tl.default_qty_on_order,
                }
            )
        create_costing_lines_from_template(job, profile, rows)

    matched = bind_costing_lines_to_bom(job)
    flash(f"Costing sheet bound to {t('parts_list')}. {matched} line(s) matched.", "success")
    return redirect(url_for("parts.job_parts", job_id=job.id))


@costing_bp.route("/jobs/<int:job_id>/costing/export", methods=["GET"])
@login_required
@roles_required("Admin", "Office")
def export_costing(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    profile = _find_active_profile(job.template_id) if job.template_id else None
    if not profile or not profile.xlsx_template_path:
        flash("No costing template file configured for this engine. Please upload a template before exporting.", "warning")
        return redirect(url_for("parts.job_parts", job_id=job.id))

    sheet = ensure_costing_sheet_from_template(job, profile)
    if not sheet:
        flash("No costing sheet available for this job.", "warning")
        return redirect(url_for("parts.job_parts", job_id=job.id))

    # Ensure lines exist; seed from template catalogue or BOM
    if not sheet.lines:
        if profile.template_lines:
            rows = []
            for tl in profile.template_lines:
                rows.append(
                    {
                        "line_no": tl.line_no,
                        "group_no": tl.group_no,
                        "figure": tl.figure,
                        "item_no": tl.item_no,
                        "oem_part_no": tl.oem_part_no,
                        "system_part_number": tl.system_part_number,
                        "part_description": tl.part_description,
                        "line_class": tl.default_class,
                        "is_menu": tl.is_menu,
                        "is_kit": tl.is_kit,
                        "is_consumable": tl.is_consumable,
                        "intended_supplier": tl.default_intended_supplier,
                        "latest_supplier": tl.default_latest_supplier,
                        "latest_cost": tl.default_latest_cost,
                        "menu_sell_price_unit": tl.default_menu_sell_price,
                        "qty_on_stock": tl.default_qty_on_stock,
                        "qty_on_order": tl.default_qty_on_order,
                        "qty_required": tl.default_qty_on_stock or 0,
                    }
                )
            create_costing_lines_from_template(job, profile, rows)
        else:
            create_costing_lines_from_bom(job)

    # Bind to BOM to pull current qty/status
    bind_costing_lines_to_bom(job)
    enrich_bom_from_catalogue(job, preserve_overrides=True)

    template_path = (profile.xlsx_template_path or "").lower()
    if template_path.endswith(".csv"):
        filename = f"Job_{job.job_number}_costing.csv"
        return _build_costing_csv_response(job, sheet, profile, filename)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp_path = tmp.name
    try:
        export_costing_sheet_xlsx(job, tmp_path)
        download_name = f"Job_{job.job_number}_costing.xlsx"
        return send_file(tmp_path, as_attachment=True, download_name=download_name)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@costing_bp.route("/jobs/<int:job_id>/costing/export_dmt", methods=["GET"])
@login_required
@roles_required("Admin", "Office")
def export_costing_dmt(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    sheet = CostingSheet.query.filter_by(job_id=job.id).first()
    if not sheet:
        abort(404)

    profile = _find_active_profile(job.template_id) if job.template_id else None
    filename = f"job_{job.job_number}_costing_dmt.csv"
    return _build_costing_csv_response(job, sheet, profile, filename)


@costing_bp.route("/admin/templates/<int:template_id>/costing/catalogue", methods=["GET", "POST"])
@login_required
@roles_required("Admin")
def costing_catalogue(template_id):
    template = _get_or_404(Template, template_id)
    profile = _find_active_profile(template.id)
    if not profile:
        flash("No active costing template profile. Upload a costing template first.", "warning")
        return redirect(url_for("templates_bp.template_edit", template_id=template.id))

    lines = (
        CostingTemplateLine.query.filter_by(costing_template_profile_id=profile.id)
        .order_by(CostingTemplateLine.line_no, CostingTemplateLine.id)
        .all()
    )

    if request.method == "POST":
        for line in lines:
            line.default_intended_supplier = (request.form.get(f"supplier_{line.id}") or "").strip() or None
            line.default_latest_supplier = (request.form.get(f"latest_supplier_{line.id}") or "").strip() or None
            line.is_menu = bool(request.form.get(f"is_menu_{line.id}"))
            line.is_kit = bool(request.form.get(f"is_kit_{line.id}"))
            line.is_consumable = bool(request.form.get(f"is_consumable_{line.id}"))

            cls_val = request.form.get(f"class_{line.id}")
            try:
                line.default_class = LineClassEnum(cls_val) if cls_val else line.default_class
            except ValueError:
                pass

            def _parse_decimal(val):
                try:
                    return Decimal(val) if val is not None and str(val).strip() else None
                except (TypeError, ValueError, InvalidOperation):
                    return None

            line.default_latest_cost = _parse_decimal(request.form.get(f"latest_cost_{line.id}"))
            line.default_menu_sell_price = _parse_decimal(request.form.get(f"menu_price_{line.id}"))
            line.default_qty_on_stock = int(request.form.get(f"qty_stock_{line.id}") or 0)
            line.default_qty_on_order = int(request.form.get(f"qty_order_{line.id}") or 0)

        db.session.commit()
        flash("Catalogue updated.", "success")
        return redirect(url_for("costing.costing_catalogue", template_id=template.id))

    return render_template(
        "costing_catalogue.html",
        template=template,
        profile=profile,
        lines=lines,
        LineClassEnum=LineClassEnum,
    )
