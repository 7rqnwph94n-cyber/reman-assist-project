import os
import io
import csv
import tempfile
import shutil
import zipfile
import random
import re
import hashlib
from math import ceil
import json
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
    send_file,
    current_app,
    abort,
    g,
)
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from models import (
    db,
    User,
    Job,
    SurveyItem,
    PartRequirement,
    Attachment,
    Template,
    RoleEnum,
    JobStatusEnum,
    DecisionEnum,
    StockStatusEnum,
    MeasurementResultEnum,
    AuditLog,
    ErrorLog,
    AppLog,
    PreSurveyResult,
    PickList,
    InvalidJobTransition,
)
from auth_utils import (
    login_required,
    roles_required,
    current_user,
    require_job_access,
    job_access_required,
    get_org_filter,
    get_scoped_or_404,
)
from services.job_services import ensure_survey_from_template, change_job_status, log_event, get_dashboard_jobs, create_job, is_job_locked
from services.job_pack_revision import bump_revision
from utils.localization import t
from services.bom import regenerate_bom_for_job
from services.bom_services import apply_supersedes
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from file_utils import (
    save_uploaded_file,
    delete_upload_file,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_MIME_TYPES,
    ALLOWED_ATTACHMENT_EXTENSIONS,
    ALLOWED_ATTACHMENT_MIME_TYPES,
)
from pdf_utils import build_job_pack_pdf
from services.job_pack_report import build_job_pack_context
from services.job_pack_export import build_job_pack_zip

jobs_bp = Blueprint("jobs", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)


# Routes
def _load_presurvey_fields(template):
    """Normalise pre-survey schema JSON into a list of dicts."""
    if not template or not template.pre_survey_schema:
        return []

    try:
        raw = json.loads(template.pre_survey_schema)
        if not isinstance(raw, list):
            return []
    except Exception:
        return []

    fields = []
    for field in raw:
        label = (field.get("label") or "").strip()
        if not label:
            continue
        ftype = (field.get("type") or "checkbox").strip().lower()
        opts_raw = field.get("options") or ""
        # allow either comma or newline separated option strings
        if isinstance(opts_raw, str):
            parts = []
            for chunk in opts_raw.replace("\r", "").split("\n"):
                parts.extend(chunk.split(","))
            options = [opt.strip() for opt in parts if opt.strip()]
        elif isinstance(opts_raw, list):
            options = [str(opt).strip() for opt in opts_raw if str(opt).strip()]
        else:
            options = []

        fields.append({"label": label, "type": ftype, "options": options})
    return fields


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_dt(value: datetime | None, fallback: datetime) -> datetime:
    if not value:
        value = fallback
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _extract_status(message: str, key: str) -> str | None:
    match = re.search(rf"{key}\\s+(\\w+)", message or "")
    if not match:
        return None
    return match.group(1)


def _build_job_flow_rows(jobs: list[Job], now: datetime) -> tuple[list[dict], dict]:
    now = _normalize_dt(now, datetime.utcnow())
    job_ids = [job.id for job in jobs]
    if not job_ids:
        return [], {}

    status_counts = (
        db.session.query(
            PartRequirement.job_id,
            PartRequirement.stock_status,
            db.func.count(PartRequirement.id),
        )
        .filter(
            PartRequirement.job_id.in_(job_ids),
            PartRequirement.stock_status.in_(
                [
                    StockStatusEnum.TO_ORDER,
                    StockStatusEnum.ORDERED,
                    StockStatusEnum.BACKORDER,
                ]
            ),
        )
        .group_by(PartRequirement.job_id, PartRequirement.stock_status)
        .all()
    )

    counts_by_job = {}
    for job_id, status, count in status_counts:
        counts = counts_by_job.setdefault(
            job_id,
            {
                "to_order": 0,
                "ordered": 0,
                "backorder": 0,
            },
        )
        if status == StockStatusEnum.TO_ORDER:
            counts["to_order"] = count
        elif status == StockStatusEnum.ORDERED:
            counts["ordered"] = count
        elif status == StockStatusEnum.BACKORDER:
            counts["backorder"] = count

    logs = (
        AuditLog.query.filter(
            AuditLog.job_id.in_(job_ids),
            AuditLog.action == "status_change",
        )
        .order_by(AuditLog.job_id, AuditLog.created_at)
        .all()
    )
    logs_by_job: dict[int, list[AuditLog]] = {}
    for log in logs:
        logs_by_job.setdefault(log.job_id, []).append(log)

    durations_by_job: dict[int, dict[str, float]] = {}
    for job in jobs:
        durations = {status.value: 0.0 for status in JobStatusEnum}
        prev_time = _normalize_dt(job.created_at, now)
        for log in logs_by_job.get(job.id, []):
            old_status = _extract_status(log.message or "", "from")
            log_time = _normalize_dt(log.created_at, prev_time)
            if old_status in durations and log_time and prev_time:
                delta = (log_time - prev_time).total_seconds()
                if delta >= 0:
                    durations[old_status] += delta
            if log_time:
                prev_time = log_time
        end_time = job.updated_at if job.status == JobStatusEnum.COMPLETE else now
        end_time = _normalize_dt(end_time, now)
        if end_time and prev_time and job.status:
            current_status = job.status.value
            if current_status in durations:
                delta = (end_time - prev_time).total_seconds()
                if delta >= 0:
                    durations[current_status] += delta
        durations_by_job[job.id] = durations

    rows = []
    for job in jobs:
        counts = counts_by_job.get(
            job.id, {"to_order": 0, "ordered": 0, "backorder": 0}
        )
        durations = durations_by_job.get(job.id, {})
        durations_raw = dict(durations)
        rows.append(
            {
                "job": job,
                "status": job.status.value if job.status else "—",
                "technician": job.assigned_to.username if job.assigned_to else "—",
                "to_order": counts["to_order"],
                "ordered": counts["ordered"],
                "backorder": counts["backorder"],
                "durations": {k: _format_duration(v) for k, v in durations.items()},
                "durations_raw": durations_raw,
                "current_status_seconds": durations_raw.get(job.status.value) if job.status else None,
            }
        )
    totals = {
        "jobs": len(jobs),
        "to_order": sum(r["to_order"] for r in rows),
        "ordered": sum(r["ordered"] for r in rows),
        "backorder": sum(r["backorder"] for r in rows),
    }
    return rows, totals


def _build_job_flow_context():
    user = current_user()
    org_id = get_org_filter()
    status_values = [status.value for status in JobStatusEnum]
    default_statuses = [
        JobStatusEnum.PRE_SURVEY.value,
        JobStatusEnum.SURVEY.value,
        JobStatusEnum.OFFICE.value,
        JobStatusEnum.BUILD.value,
        JobStatusEnum.HOLD.value,
    ]
    selected_statuses = request.args.getlist("status") or default_statuses
    selected_statuses = [s for s in selected_statuses if s in status_values]
    if not selected_statuses:
        selected_statuses = default_statuses

    tech_id = request.args.get("technician") or ""
    engine_type = request.args.get("engine_type") or ""
    created_from = _parse_date(request.args.get("created_from"))
    created_to = _parse_date(request.args.get("created_to"))

    query = Job.query
    if org_id:
        query = query.filter(Job.organization_id == org_id)
    if selected_statuses:
        query = query.filter(Job.status.in_(selected_statuses))
    if tech_id:
        try:
            query = query.filter(Job.assigned_to_id == int(tech_id))
        except ValueError:
            pass
    if engine_type:
        query = query.filter(Job.engine_type == engine_type)
    if created_from:
        query = query.filter(Job.created_at >= created_from)
    if created_to:
        created_to_end = created_to + timedelta(days=1)
        query = query.filter(Job.created_at < created_to_end)

    jobs = (
        query
        .options(selectinload(Job.assigned_to), selectinload(Job.template))
        .order_by(Job.created_at.desc())
        .all()
    )
    now = datetime.now(timezone.utc)
    rows, totals = _build_job_flow_rows(jobs, now)

    technicians_query = User.query.filter(User.role == RoleEnum.TECHNICIAN)
    if org_id:
        technicians_query = technicians_query.filter(User.organization_id == org_id)
    technicians = technicians_query.order_by(User.username).all()
    engine_types_query = db.session.query(Job.engine_type)
    if org_id:
        engine_types_query = engine_types_query.filter(Job.organization_id == org_id)
    engine_types = sorted({et for (et,) in engine_types_query.distinct().all() if et})

    status_labels = {
        JobStatusEnum.PRE_SURVEY.value: t("pre_inspection"),
        JobStatusEnum.SURVEY.value: t("inspection_caps"),
        JobStatusEnum.OFFICE.value: "Office",
        JobStatusEnum.BUILD.value: "Build",
        JobStatusEnum.HOLD.value: "Hold",
        JobStatusEnum.COMPLETE.value: "Complete",
    }

    return {
        "jobs": jobs,
        "rows": rows,
        "totals": totals,
        "status_values": status_values,
        "status_labels": status_labels,
        "selected_statuses": selected_statuses,
        "technicians": technicians,
        "engine_types": engine_types,
        "filters": {
            "technician": tech_id,
            "engine_type": engine_type,
            "created_from": request.args.get("created_from") or "",
            "created_to": request.args.get("created_to") or "",
        },
    }


@jobs_bp.route("/dashboard")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def dashboard():
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    if user.role == RoleEnum.STORES:
        return redirect(url_for("stores.stores_hub", view="master"))

    limit = request.args.get("limit", "25")
    try:
        per_status_limit = max(1, min(int(limit), 100))
    except ValueError:
        per_status_limit = 25
    search_query = request.args.get("q", "").strip() or None
    stage = (request.args.get("stage") or "").strip().lower()
    stage_map = {
        "pre_survey": JobStatusEnum.PRE_SURVEY,
        "survey": JobStatusEnum.SURVEY,
        "office": JobStatusEnum.OFFICE,
        "build": JobStatusEnum.BUILD,
        "complete": JobStatusEnum.COMPLETE,
    }
    status_filter = stage_map.get(stage)
    sort_by = (request.args.get("sort") or "").strip().lower()
    if sort_by not in {"updated", "created", ""}:
        sort_by = ""
    jobs_by_status, _nc_counts, procurement_counts, status_totals = get_dashboard_jobs(
        user,
        per_status_limit=per_status_limit,
        search_query=search_query,
        status_filter=status_filter,
        sort_by=sort_by or None,
    )

    active_statuses = {JobStatusEnum.OFFICE, JobStatusEnum.BUILD}
    base_active_query = Job.query.filter(Job.status.in_(list(active_statuses)))
    if user and user.current_organization_id:
        base_active_query = base_active_query.filter(Job.organization_id == user.current_organization_id)

    waiting_parts_ids = (
        base_active_query
        .filter(
            db.session.query(PartRequirement.id).filter(
                PartRequirement.job_id == Job.id,
                PartRequirement.stock_status.notin_([
                    StockStatusEnum.RECEIVED,
                    StockStatusEnum.FITTED,
                    StockStatusEnum.IN_STOCK,
                ]),
            ).exists()
        )
        .with_entities(Job.id)
        .all()
    )
    waiting_parts_ids = {jid for (jid,) in waiting_parts_ids}

    waiting_machining_ids = (
        base_active_query
        .filter(
            db.session.query(SurveyItem.id).filter(
                SurveyItem.job_id == Job.id,
                SurveyItem.decision == DecisionEnum.MACHINING,
                SurveyItem.is_resolved.is_(False),
            ).exists()
        )
        .with_entities(Job.id)
        .all()
    )
    waiting_machining_ids = {jid for (jid,) in waiting_machining_ids}

    bottleneck_counts = {
        "parts": len(waiting_parts_ids),
        "machining": len(waiting_machining_ids),
    }

    bottleneck_map = {}
    for jobs in jobs_by_status.values():
        for job in jobs:
            parts_flag = job.id in waiting_parts_ids
            machining_flag = job.id in waiting_machining_ids
            if parts_flag and machining_flag:
                bottleneck_map[job.id] = "both"
            elif parts_flag:
                bottleneck_map[job.id] = "parts"
            elif machining_flag:
                bottleneck_map[job.id] = "machining"
            else:
                bottleneck_map[job.id] = ""

    user_role = user.role.value

    return render_template(
        "dashboard.html",
        user_role=user_role,
        pre_survey_jobs=jobs_by_status["Pre-survey"],
        survey_jobs=jobs_by_status["Survey"],
        office_jobs=jobs_by_status["Office"],
        build_jobs=jobs_by_status["Build"],
        complete_jobs=jobs_by_status["Complete"],
        jobs_by_status=jobs_by_status,
        procurement_counts=procurement_counts,
        per_status_limit=per_status_limit,
        status_totals=status_totals,
        search_query=search_query,
        stage_filter=stage or None,
        sort_by=sort_by or None,
        bottleneck_counts=bottleneck_counts,
        bottleneck_map=bottleneck_map,
    )


@jobs_bp.route("/jobs")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def jobs_list():
    user = current_user()
    q = Job.query.order_by(Job.created_at.desc())
    org_id = get_org_filter()
    q = q.filter(Job.organization_id == org_id)
    if user and user.role == RoleEnum.TECHNICIAN:
        q = q.filter(Job.assigned_to_id == user.id)
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    per_page = 50
    total = q.count()
    total_pages = max(1, ceil(total / per_page)) if total else 1
    jobs = (
        q.options(selectinload(Job.assigned_to), selectinload(Job.template))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return render_template(
        "jobs_list.html",
        jobs=jobs,
        page=page,
        total_pages=total_pages,
        total=total,
    )


@jobs_bp.route("/jobs/create", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_create():
    user = current_user()
    org_id = get_org_filter()

    if request.method == "POST":
        job_number = (request.form.get("job_number") or "").strip()
        customer_name = (request.form.get("customer_name") or "").strip()
        engine_type = (request.form.get("engine_type") or "").strip()
        serial_number = (request.form.get("serial_number") or "").strip()
        template_id = request.form.get("template_id") or ""
        assigned_to_id = request.form.get("assigned_to_id") or ""

        try:
            job = create_job(
                job_number=job_number,
                customer_name=customer_name,
                engine_type=engine_type,
                serial_number=serial_number,
                template_id=template_id,
                assigned_to_id=assigned_to_id,
                user_id=user.id,
            )
            flash("Job created.", "success")
            return redirect(url_for("jobs.jobs_list"))
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("jobs.job_create"))

    technicians = (
        User.query.filter(User.role.in_([RoleEnum.TECHNICIAN, RoleEnum.ADMIN]))
        .filter(User.organization_id == org_id)
        .order_by(User.username)
        .all()
    )
    templates = Template.query.filter(Template.organization_id == org_id).order_by(Template.name).all()

    return render_template(
        "create_job.html",
        technicians=technicians,
        templates=templates,
    )


@jobs_bp.route("/jobs/<int:job_id>")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def job_detail(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    survey_items = (
        SurveyItem.query.filter_by(job_id=job.id)
        .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
        .all()
    )
    parts = PartRequirement.query.filter_by(job_id=job.id).all()
    attachments = Attachment.query.filter_by(job_id=job.id).all()
    return render_template(
        "job_detail.html",
        job=job,
        survey_items=survey_items,
        parts=parts,
        attachments=attachments,
    )


@jobs_bp.route("/admin/jobs/<int:job_id>/status", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def admin_override_status(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    new_status_raw = (request.form.get("status") or "").strip()
    if not new_status_raw:
        flash("No status selected.", "danger")
        return redirect(url_for("jobs.job_detail", job_id=job.id))
    try:
        new_status = JobStatusEnum(new_status_raw)
    except ValueError:
        flash("Invalid status.", "danger")
        return redirect(url_for("jobs.job_detail", job_id=job.id))

    reason = (request.form.get("reason") or "").strip() or "Admin override"
    try:
        change_job_status(job, new_status, user=current_user(), reason=reason)
    except InvalidJobTransition as exc:
        flash(str(exc), "danger")
        return redirect(url_for("jobs.job_detail", job_id=job.id))
    log_event(
        action="status_override",
        message=f"Status override to {new_status.value}",
        job=job,
        user=current_user(),
        details=reason,
    )
    db.session.commit()
    flash("Job status updated.", "success")
    return redirect(url_for("jobs.job_detail", job_id=job.id))


@jobs_bp.route("/jobs/<int:job_id>/pre_survey", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.TECHNICIAN.value, RoleEnum.ADMIN.value)
def job_pre_survey(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    flag_key = f"pre_survey_done_{job.id}"
    fields = _load_presurvey_fields(job.template)
    result = PreSurveyResult.query.filter_by(job_id=job.id).first()

    existing_data = {}
    existing_notes = None
    existing_photo = None
    if result:
        session[flag_key] = True  # let users back in without repeating the form
        if result.data:
            try:
                existing_data = json.loads(result.data) or {}
            except Exception:
                existing_data = {}
        existing_notes = result.notes
        if result.thumbnail_path:
            existing_photo = url_for("uploaded_file", filename=result.thumbnail_path)

    if request.method == "POST":
        answers = {}
        for idx, field in enumerate(fields, start=1):
            form_key = f"field_{idx}"
            label = field["label"]
            ftype = field.get("type") or "checkbox"

            if ftype == "checkbox":
                answers[label] = bool(request.form.get(form_key))
            else:
                val = (request.form.get(form_key) or "").strip()
                answers[label] = val

        notes = (request.form.get("notes") or "").strip() or None
        photo_file = request.files.get("photo")
        photo_path = None
        if photo_file and photo_file.filename:
            try:
                photo_path = save_uploaded_file(
                    photo_file,
                    subdir=str(job.id),
                    allowed_exts=ALLOWED_IMAGE_EXTENSIONS,
                    allowed_mimetypes=ALLOWED_IMAGE_MIME_TYPES,
                    require_image=True,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("jobs.job_pre_survey", job_id=job.id))

        if not result:
            result = PreSurveyResult(job_id=job.id)

        result.data = json.dumps(answers)
        result.notes = notes
        if photo_path:
            result.thumbnail_path = photo_path
        result.completed_at = datetime.now(timezone.utc)
        db.session.add(result)
        log_event(
            action="pre_survey_saved",
            message=f"{t('pre_inspection')} completed",
            job=job,
            user=current_user(),
        )
        db.session.commit()

        session[flag_key] = True
        flash(f"{t('pre_inspection')} saved.", "success")
        return redirect(url_for("survey.job_survey", job_id=job.id))

    return render_template(
        "job_pre_survey.html",
        job=job,
        presurvey_fields=fields,
        existing_data=existing_data,
        existing_notes=existing_notes,
        existing_photo=existing_photo,
    )


@jobs_bp.route("/jobs/<int:job_id>/pack")
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def job_pack(job_id):
    job = _get_or_404(Job, job_id)
    survey_items = (
        SurveyItem.query.filter_by(job_id=job.id)
        .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
        .all()
    )
    parts = (
        PartRequirement.query.filter_by(job_id=job.id)
        .order_by(PartRequirement.section, PartRequirement.pos, PartRequirement.id)
        .all()
    )
    attachments = Attachment.query.filter_by(job_id=job.id).all()
    audit_logs = (
        AuditLog.query.filter_by(job_id=job.id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
        .all()
    )
    pre_photo_url = None
    if getattr(job, "pre_survey_result", None) and job.pre_survey_result.thumbnail_path:
        pre_photo_url = url_for(
            "uploaded_file", filename=job.pre_survey_result.thumbnail_path
        )

    total_lines = len(survey_items)
    always_replace_count = sum(1 for s in survey_items if s.always_replace)
    big_ticket_count = sum(1 for s in survey_items if getattr(s, "big_ticket", False))
    test_count = sum(1 for s in survey_items if getattr(s, "requires_test", False))

    good_count = sum(1 for s in survey_items if s.decision == DecisionEnum.REUSE)
    replace_count = sum(1 for s in survey_items if s.decision == DecisionEnum.REPLACE)
    scrap_count = sum(1 for s in survey_items if s.decision == DecisionEnum.SCRAP)
    undecided_count = sum(1 for s in survey_items if s.decision is None)

    survey_counts = {
        "total": total_lines,
        "always": always_replace_count,
        "big_ticket": big_ticket_count,
        "test": test_count,
        "good": good_count,
        "replace": replace_count,
        "scrap": scrap_count,
        "undecided": undecided_count,
    }

    presurvey_data = {}
    presurvey_notes = None
    presurvey_completed_at = None
    if getattr(job, "pre_survey_result", None):
        psr = job.pre_survey_result
        if psr.data:
            try:
                presurvey_data = json.loads(psr.data) or {}
            except Exception:
                presurvey_data = {}
        presurvey_notes = psr.notes
        presurvey_completed_at = psr.completed_at

    return render_template(
        "job_pack.html",
        job=job,
        survey_items=survey_items,
        parts=parts,
        attachments=attachments,
        survey_counts=survey_counts,
        audit_logs=audit_logs,
        pre_photo_url=pre_photo_url,
        presurvey_data=presurvey_data,
        presurvey_notes=presurvey_notes,
        presurvey_completed_at=presurvey_completed_at,
    )


@jobs_bp.route("/jobs/<int:job_id>/bom/regenerate", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_regenerate_bom(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    items = (
        SurveyItem.query.filter_by(job_id=job.id)
        .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
        .all()
    )
    created = regenerate_bom_for_job(job, items, request.form)
    apply_supersedes(job.id)
    log_event(
        action="bom_regenerated",
        message=f"Regenerated {t('parts_list')} with {created} line(s)",
        job=job,
        user=current_user(),
    )
    bump_revision(job, "bom_regenerated", user=current_user())
    db.session.commit()
    if created:
        flash(f"{t('parts_list')} regenerated – {created} line(s) created.", "success")
    else:
        flash(f"{t('parts_list')} regenerated – no lines created (no replace/scrap items).", "info")
    return redirect(url_for("jobs.job_pack", job_id=job.id))


@jobs_bp.route("/jobs/<int:job_id>/report")
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_report(job_id):
    job = _get_or_404(Job, job_id)
    view_mode = (request.args.get("view") or "internal").lower()
    if view_mode not in {"internal", "customer"}:
        view_mode = "internal"
    requester = current_user().username if current_user() else None
    context = build_job_pack_context(job.id, view_mode=view_mode, requested_by=requester)
    return render_template("reports/job_pack_report.html", **context)


@jobs_bp.route("/jobs/<int:job_id>/report.pdf")
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_report_pdf(job_id):
    job = _get_or_404(Job, job_id)
    view_mode = (request.args.get("view") or "internal").lower()
    if view_mode not in {"internal", "customer"}:
        view_mode = "internal"
    requester = current_user().username if current_user() else None
    context = build_job_pack_context(job.id, view_mode=view_mode, requested_by=requester)
    if context.get("report_incomplete"):
        msg = (
            "Export Blocked: Report contains critical data errors. "
            "Please resolve the highlighted issues before generating the final Job Pack."
        )
        flash(msg, "danger")
        try:
            user = current_user()
            db.session.add(
                AppLog(
                    job_id=job.id,
                    user_id=user.id if user else None,
                    request_id=getattr(g, "request_id", None),
                    level="critical",
                    message="Report export blocked: " + "; ".join(context.get("report_errors", [])),
                )
            )
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        resp = redirect(url_for("jobs.job_report", job_id=job.id, view=view_mode))
        resp.status_code = 409
        return resp

    from services.pdf_renderer import render_report_pdf

    html = render_template("reports/job_pack_report.html", **context)
    css_path = os.path.join(current_app.root_path, "static", "css", "report.css")
    try:
        pdf = render_report_pdf(html, request.url_root, css_path)
    except RuntimeError as exc:
        flash(f"PDF export failed: {exc}. See README for PDF dependencies.", "danger")
        return redirect(url_for("jobs.job_report", job_id=job.id, view=view_mode))

    log_event(
        action="job_pack_export_pdf",
        message=f"{t('work_order_caps')} PDF exported ({view_mode})",
        job=job,
        user=current_user(),
    )
    bump_revision(job, f"job_pack_export_pdf:{view_mode}", user=current_user())
    db.session.commit()

    report_prefix = t("work_order_caps").replace(" ", "")
    filename = f"{report_prefix}_{job.job_number}_{view_mode}.pdf"
    return send_file(
        io.BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@jobs_bp.route("/jobs/<int:job_id>/export.zip")
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_report_pack(job_id):
    job = _get_or_404(Job, job_id)
    view_mode = (request.args.get("view") or "internal").lower()
    if view_mode not in {"internal", "customer"}:
        view_mode = "internal"
    include_arg = request.args.get("include_bom")
    if include_arg is None:
        include_bom = view_mode != "customer"
    else:
        include_bom = include_arg != "0"
    try:
        zip_bytes = build_job_pack_zip(
            job,
            view_mode=view_mode,
            include_bom=include_bom,
            requested_by=current_user().username if current_user() else None,
        )
    except RuntimeError as exc:
        flash(f"Pack export failed: {exc}. See README for PDF dependencies.", "danger")
        return redirect(url_for("jobs.job_report", job_id=job.id, view=view_mode))

    log_event(
        action="job_pack_export_zip",
        message=f"{t('work_order_caps')} ZIP exported ({view_mode})",
        job=job,
        user=current_user(),
    )
    bump_revision(job, f"job_pack_export_zip:{view_mode}", user=current_user())
    db.session.commit()

    report_prefix = t("work_order_caps").replace(" ", "")
    filename = f"{report_prefix}_{job.job_number}_{view_mode}.zip"
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


@jobs_bp.route("/reports/job_flow")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_flow_report():
    context = _build_job_flow_context()
    csv_args = request.args.to_dict(flat=False)
    csv_url = url_for("jobs.job_flow_report_csv", **csv_args)
    context["csv_url"] = csv_url
    return render_template("reports/job_flow_report.html", **context)


@jobs_bp.route("/reports/job_flow.csv")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_flow_report_csv():
    context = _build_job_flow_context()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Job number",
            "Customer",
            "Engine type",
            "Status",
            "Technician",
            "To order",
            "Ordered",
            "Backorder",
            f"{t('pre_inspection')} time",
            f"{t('inspection_caps')} time",
            "Office time",
            "Build time",
            "Hold time",
            "Created at",
            "Bottleneck_Type",
            "Days_In_Status",
        ]
    )
    for row in context["rows"]:
        job = row["job"]
        durations = row["durations"]
        seconds_in_status = row.get("current_status_seconds") or 0
        days_in_status = round(seconds_in_status / 86400, 1) if seconds_in_status else 0
        writer.writerow(
            [
                job.job_number,
                job.customer_name or "",
                job.engine_type or "",
                row["status"],
                row["technician"],
                row["to_order"],
                row["ordered"],
                row["backorder"],
                durations.get(JobStatusEnum.PRE_SURVEY.value, "—"),
                durations.get(JobStatusEnum.SURVEY.value, "—"),
                durations.get(JobStatusEnum.OFFICE.value, "—"),
                durations.get(JobStatusEnum.BUILD.value, "—"),
                durations.get(JobStatusEnum.HOLD.value, "—"),
                job.created_at.isoformat() if job.created_at else "",
                job.bottleneck_type() if hasattr(job, "bottleneck_type") else "",
                days_in_status,
            ]
        )
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="job_flow_report.csv",
    )


@jobs_bp.route("/jobs/<int:job_id>/build", methods=["GET", "POST"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.TECHNICIAN.value)
def job_build(job_id):
    job = _get_or_404(Job, job_id)
    user = current_user()
    if user.role not in [RoleEnum.TECHNICIAN, RoleEnum.ADMIN]:
        flash("Build view is limited to technicians and admins.", "danger")
        return redirect(url_for("jobs.job_detail", job_id=job.id))

    if request.method == "POST":
        if is_job_locked(job, user):
            flash("Job is complete and read-only. Admin can reopen if needed.", "warning")
            return redirect(url_for("jobs.job_build", job_id=job.id))
        action = request.form.get("action")
        if action == "start_build":
            try:
                change_job_status(job, JobStatusEnum.BUILD)
            except InvalidJobTransition as exc:
                flash(str(exc), "danger")
                return redirect(url_for("jobs.job_build", job_id=job.id))
            db.session.commit()
            flash("Build started.", "success")
            return redirect(url_for("jobs.job_build", job_id=job.id))
        if action == "complete_build":
            try:
                change_job_status(job, JobStatusEnum.COMPLETE)
            except InvalidJobTransition as exc:
                flash(str(exc), "danger")
                return redirect(url_for("jobs.job_build", job_id=job.id))
            db.session.commit()
            flash("Build marked complete.", "success")
            return redirect(url_for("jobs.job_build", job_id=job.id))
        if action == "add_note":
            note = (request.form.get("note") or "").strip()
            if note:
                log = AuditLog(
                    job_id=job.id,
                    user_id=user.id if user else None,
                    action="build_note",
                    message=note,
                )
                db.session.add(log)
                db.session.commit()
                flash("Build note added.", "success")
            return redirect(url_for("jobs.job_build", job_id=job.id))

    parts = PartRequirement.query.filter_by(job_id=job.id).all()
    picklists = (
        PickList.query.filter_by(job_id=job.id)
        .order_by(PickList.created_at.desc())
        .all()
    )
    attachments = (
        Attachment.query.filter_by(job_id=job.id)
        .order_by(Attachment.uploaded_at.desc())
        .all()
    )
    build_notes = (
        AuditLog.query.filter_by(job_id=job.id, action="build_note")
        .order_by(AuditLog.created_at.desc())
        .limit(10)
        .all()
    )

    readiness = {
        "in_stock": 0,
        "to_order": 0,
        "ordered": 0,
        "received": 0,
        "fitted": 0,
        "pending": 0,
    }
    for p in parts:
        status_val = p.stock_status.value if p.stock_status else StockStatusEnum.PENDING.value
        if status_val in readiness:
            readiness[status_val] += 1
        else:
            readiness["pending"] += 1

    return render_template(
        "job_build.html",
        job=job,
        parts=parts,
        readiness=readiness,
        picklists=picklists,
        attachments=attachments,
        build_notes=build_notes,
        read_only=is_job_locked(job, user),
    )


@jobs_bp.route("/jobs/<int:job_id>/parts/status-summary", methods=["GET"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.TECHNICIAN.value)
def job_parts_status_summary(job_id):
    job = _get_or_404(Job, job_id)

    parts = PartRequirement.query.filter_by(job_id=job.id).all()
    total_required = len(parts)
    arrived_statuses = {
        StockStatusEnum.RECEIVED,
        StockStatusEnum.FITTED,
        StockStatusEnum.IN_STOCK,
    }
    total_arrived = sum(1 for p in parts if p.stock_status in arrived_statuses)

    recent = (
        PartRequirement.query
        .filter(
            PartRequirement.job_id == job.id,
            PartRequirement.stock_status.in_([s.value for s in arrived_statuses]),
        )
        .order_by(
            PartRequirement.received_at.desc().nullslast(),
            PartRequirement.updated_at.desc(),
        )
        .first()
    )
    recent_name = recent.name or recent.part_no or "" if recent else ""
    recent_part_no = recent.part_no or "" if recent else ""

    return jsonify({
        "total_required": total_required,
        "total_arrived": total_arrived,
        "recent_arrival": recent_name,
        "recent_part_no": recent_part_no,
    })


@jobs_bp.route("/admin/jobs/<int:job_id>/autofill_survey", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def admin_autofill_survey(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    ensure_survey_from_template(job)
    survey_items = SurveyItem.query.filter_by(job_id=job.id).all()

    for item in survey_items:
        if item.always_replace:
            item.decision = DecisionEnum.REPLACE
        else:
            item.decision = random.choice(
                [DecisionEnum.REUSE, DecisionEnum.REPLACE, DecisionEnum.SCRAP]
            )

    bump_revision(job, "survey_autofill", user=current_user())
    db.session.commit()
    flash(f"{t('inspection_caps')} auto-filled for testing.", "success")
    return redirect(url_for("survey.job_survey", job_id=job.id))


@jobs_bp.route("/admin/jobs/<int:job_id>/mark_all_good", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def admin_mark_all_good(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    ensure_survey_from_template(job)
    survey_items = SurveyItem.query.filter_by(job_id=job.id).all()

    for item in survey_items:
        if item.always_replace:
            item.decision = DecisionEnum.REPLACE
        else:
            item.decision = DecisionEnum.REUSE

    bump_revision(job, "survey_mark_all_good", user=current_user())
    db.session.commit()
    flash(f"All {t('inspection_lines')} marked Good (100% items kept as Replace).", "success")
    return redirect(url_for("survey.job_survey", job_id=job.id))


@jobs_bp.route("/jobs/<int:job_id>/attachments", methods=["GET", "POST"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def job_attachments(job_id):
    job = _get_or_404(Job, job_id)

    if request.method == "POST":
        if is_job_locked(job, current_user()):
            flash("Job is complete and read-only. Admin can reopen if needed.", "warning")
            return redirect(url_for("jobs.job_attachments", job_id=job.id))
        upload = request.files.get("file")
        if not upload or upload.filename == "":
            flash("No file selected.", "danger")
            return redirect(url_for("jobs.job_attachments", job_id=job.id))

        try:
            rel_path = save_uploaded_file(
                upload,
                subdir=str(job.id),
                allowed_exts=ALLOWED_ATTACHMENT_EXTENSIONS,
                allowed_mimetypes=ALLOWED_ATTACHMENT_MIME_TYPES,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("jobs.job_attachments", job_id=job.id))
        file_hash = None
        if rel_path:
            abs_path = os.path.abspath(os.path.join(current_app.config["UPLOAD_FOLDER"], rel_path))
            try:
                hasher = hashlib.sha256()
                with open(abs_path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        hasher.update(chunk)
                file_hash = hasher.hexdigest()
            except OSError:
                file_hash = None
        if file_hash:
            existing = Attachment.query.filter_by(job_id=job.id, file_hash=file_hash).first()
            if existing:
                delete_upload_file(rel_path)
                flash("Duplicate attachment detected; upload skipped.", "warning")
                return redirect(url_for("jobs.job_attachments", job_id=job.id))
        stored_name = os.path.basename(rel_path) if rel_path else upload.filename
        att = Attachment(
            job_id=job.id,
            filename=stored_name,
            original_filename=upload.filename,
            file_path=rel_path,
            file_type=upload.mimetype,
            file_hash=file_hash,
            uploaded_by_id=current_user().id if current_user() else None,
        )
        db.session.add(att)
        log_event(
            action="attachment_uploaded",
            message=f"Attachment uploaded: {upload.filename}",
            job=job,
            user=current_user(),
        )
        bump_revision(job, "attachment_added", user=current_user())
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            msg = str(exc.orig)
            if constraint == "uq_attachments_job_file_hash" or "uq_attachments_job_file_hash" in msg:
                if rel_path:
                    delete_upload_file(rel_path)
                flash("Duplicate attachment detected; upload skipped.", "warning")
                return redirect(url_for("jobs.job_attachments", job_id=job.id))
            raise
        flash("Attachment uploaded.", "success")
        return redirect(url_for("jobs.job_attachments", job_id=job.id))

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    per_page = int(current_app.config.get("ATTACHMENTS_PAGE_SIZE", 24))
    per_page = max(1, min(per_page, 100))
    query = Attachment.query.filter_by(job_id=job.id).order_by(Attachment.uploaded_at.desc())
    total = query.count()
    total_pages = max(1, ceil(total / per_page)) if total else 1
    attachments = query.offset((page - 1) * per_page).limit(per_page).all()
    return render_template(
        "job_attachments.html",
        job=job,
        attachments=attachments,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total=total,
        read_only=is_job_locked(job, current_user()),
    )


@jobs_bp.route("/jobs/<int:job_id>/export", methods=["GET"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_export(job_id):
    if not current_app.config.get("ENABLE_LEGACY_EXPORT", False):
        abort(404)
    job = _get_or_404(Job, job_id)
    require_job_access(job)

    survey_items = (
        SurveyItem.query
        .filter_by(job_id=job.id)
        .order_by(SurveyItem.section, SurveyItem.pos)
        .all()
    )
    parts = (
        PartRequirement.query
        .filter_by(job_id=job.id)
        .order_by(PartRequirement.part_no)
        .all()
    )
    attachments = Attachment.query.filter_by(job_id=job.id).all()

    base_dir = tempfile.mkdtemp(prefix=f"job_{job.job_number}_")
    try:
        report_prefix = t("work_order_caps").replace(" ", "")
        pdf_path = os.path.join(base_dir, f"{report_prefix}_{job.job_number}.pdf")
        build_job_pack_pdf(job, survey_items, parts, attachments, output_path=pdf_path)

        inspection_dir = os.path.join(base_dir, t("inspection").replace(" ", "_"))
        os.makedirs(inspection_dir, exist_ok=True)
        survey_csv_path = os.path.join(inspection_dir, f"{t('inspection').replace(' ', '_')}_items.csv")
        with open(survey_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Section",
                    "Pos",
                    "Part no",
                    "Qty",
                    "Name",
                    "Decision",
                    "Notes",
                ]
            )
            for si in survey_items:
                dec = si.decision.name if si.decision is not None else ""
                writer.writerow(
                    [
                        si.section or "",
                        si.pos or "",
                        si.part_no or "",
                        si.qty or "",
                        si.name or "",
                        dec,
                        si.notes or "",
                    ]
                )

        parts_dir = os.path.join(base_dir, "parts")
        os.makedirs(parts_dir, exist_ok=True)
        parts_csv_path = os.path.join(parts_dir, "parts_list.csv")
        with open(parts_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Part no",
                    "Name",
                    "Qty required",
                    "Stock status",
                    "Notes",
                ]
            )
            for p in parts:
                stock = p.stock_status
                if stock is not None:
                    stock_val = getattr(stock, "value", None) or getattr(
                        stock, "name", None
                    )
                else:
                    stock_val = ""
                writer.writerow(
                    [
                        p.part_no or "",
                        p.name or "",
                        p.qty_required or "",
                        stock_val,
                        p.notes or "",
                    ]
                )

        attachments_dir = os.path.join(base_dir, "attachments")
        os.makedirs(attachments_dir, exist_ok=True)

        index_csv_path = os.path.join(attachments_dir, "attachments_index.csv")
        with open(index_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Stored filename",
                    "Original filename",
                    "Uploaded by",
                    "Uploaded at",
                ]
            )
            for a in attachments:
                uploader = a.uploaded_by.username if getattr(a, "uploaded_by", None) else ""
                writer.writerow(
                    [
                        a.filename,
                        getattr(a, "original_filename", "") or "",
                        uploader,
                        a.uploaded_at.isoformat() if getattr(a, "uploaded_at", None) else "",
                    ]
                )

                stored_rel = a.file_path or a.filename
                if stored_rel:
                    src = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_rel)
                    dest_name = os.path.basename(stored_rel)
                    if os.path.exists(src):
                        shutil.copy(src, os.path.join(attachments_dir, dest_name))

        zip_basename = f"{report_prefix}_{job.job_number}_pack"
        zip_path = shutil.make_archive(
            base_name=os.path.join(base_dir, zip_basename),
            format="zip",
            root_dir=base_dir,
        )

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=f"{zip_basename}.zip",
        )
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


@jobs_bp.route("/jobs/<int:job_id>/release", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def release_job(job_id):
    job = _get_or_404(Job, job_id)
    require_job_access(job)
    job.release_signed_by_id = current_user().id if current_user() else None
    job.release_signed_at = datetime.now(timezone.utc)
    # Optionally move status to COMPLETE if not already there
    if job.status != JobStatusEnum.COMPLETE:
        try:
            change_job_status(
                job,
                JobStatusEnum.COMPLETE,
                user=current_user(),
                reason=f"{t('work_order_caps')} released",
            )
        except InvalidJobTransition as exc:
            flash(str(exc), "danger")
            return redirect(url_for("jobs.job_pack", job_id=job.id))

    log_event(
        action="release_signed",
        message=f"{t('work_order_caps')} released / signed off",
        job=job,
        user=current_user(),
    )
    bump_revision(job, "release_signed", user=current_user())

    db.session.commit()
    flash(f"{t('work_order_caps')} released.", "success")
    return redirect(url_for("jobs.job_pack", job_id=job.id))


from sqlalchemy import func


@jobs_bp.route("/kpi")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def kpi_dashboard():
    """
    Show Key Performance Indicators for the admin dashboard.
    """
    now = datetime.now(timezone.utc)
    now_norm = _normalize_dt(now, datetime.utcnow())

    created_from = _parse_date(request.args.get("created_from"))
    created_to = _parse_date(request.args.get("created_to"))
    engine_type = request.args.get("engine_type") or ""
    tech_id = request.args.get("technician") or ""

    filters = []
    org_id = get_org_filter()
    filters.append(Job.organization_id == org_id)
    if engine_type:
        filters.append(Job.engine_type == engine_type)
    if tech_id:
        try:
            filters.append(Job.assigned_to_id == int(tech_id))
        except ValueError:
            pass
    if created_from:
        filters.append(Job.created_at >= created_from)
    if created_to:
        created_to_end = created_to + timedelta(days=1)
        filters.append(Job.created_at < created_to_end)

    total_jobs = db.session.query(func.count(Job.id)).filter(*filters).scalar()

    jobs_by_status = (
        db.session.query(Job.status, func.count(Job.id))
        .filter(*filters)
        .group_by(Job.status)
        .all()
    )
    jobs_by_status_dict = {status.value if status else "N/A": count for status, count in jobs_by_status}

    jobs = Job.query.filter(*filters).all()
    job_ids = [job.id for job in jobs]

    active_jobs = [job for job in jobs if job.status != JobStatusEnum.COMPLETE]
    ages = []
    for job in active_jobs:
        created_at = _normalize_dt(job.created_at, now_norm)
        delta = (now_norm - created_at).total_seconds()
        if delta >= 0:
            ages.append(delta / 86400)
    average_job_age = round(sum(ages) / len(ages), 1) if ages else 0

    top_replaced_parts = []
    if job_ids:
        top_replaced_parts = (
            db.session.query(
                SurveyItem.part_no,
                SurveyItem.name,
                func.count(SurveyItem.id).label("replace_count"),
            )
            .filter(
                SurveyItem.decision == DecisionEnum.REPLACE,
                SurveyItem.job_id.in_(job_ids),
            )
            .group_by(SurveyItem.part_no, SurveyItem.name)
            .order_by(func.count(SurveyItem.id).desc())
            .limit(5)
            .all()
        )

    from collections import defaultdict

    status_durations = defaultdict(list)
    logs_by_job = defaultdict(list)
    if job_ids:
        logs = (
            AuditLog.query.filter(
                AuditLog.action == "status_change",
                AuditLog.job_id.in_(job_ids),
            )
            .order_by(AuditLog.job_id, AuditLog.created_at)
            .all()
        )
        for log in logs:
            logs_by_job[log.job_id].append(log)

    for job in jobs:
        prev_time = _normalize_dt(job.created_at, now_norm)
        completion_time = None
        for log in logs_by_job.get(job.id, []):
            log_time = _normalize_dt(log.created_at, prev_time)
            old_status_val = _extract_status(log.message or "", "from")
            if old_status_val in JobStatusEnum._value2member_map_:
                delta = (log_time - prev_time).total_seconds()
                if delta >= 0:
                    status_durations[old_status_val].append(delta)
            new_status_val = _extract_status(log.message or "", "to")
            if new_status_val == JobStatusEnum.COMPLETE.value:
                completion_time = log_time
            prev_time = log_time

        end_time = completion_time
        if not end_time:
            end_time = job.updated_at if job.status == JobStatusEnum.COMPLETE else now_norm
        end_time = _normalize_dt(end_time, now_norm)
        if job.status and job.status.value in JobStatusEnum._value2member_map_:
            delta = (end_time - prev_time).total_seconds()
            if delta >= 0:
                status_durations[job.status.value].append(delta)

    avg_cycle_times = {}
    for status, durations in status_durations.items():
        if durations:
            avg_seconds = sum(durations) / len(durations)
            avg_days = avg_seconds / 86400
            if avg_days >= 1:
                avg_cycle_times[status] = f"{avg_days:.1f} days"
            else:
                avg_hours = avg_days * 24
                avg_cycle_times[status] = f"{avg_hours:.1f} hours"

    backlog_counts = {"to_order": 0, "ordered": 0, "backorder": 0}
    if job_ids:
        backlog_rows = (
            db.session.query(
                PartRequirement.stock_status,
                func.count(PartRequirement.id),
            )
            .filter(
                PartRequirement.job_id.in_(job_ids),
                PartRequirement.stock_status.in_(
                    [
                        StockStatusEnum.TO_ORDER,
                        StockStatusEnum.ORDERED,
                        StockStatusEnum.BACKORDER,
                    ]
                ),
            )
            .group_by(PartRequirement.stock_status)
            .all()
        )
        for status, count in backlog_rows:
            if status == StockStatusEnum.TO_ORDER:
                backlog_counts["to_order"] = count
            elif status == StockStatusEnum.ORDERED:
                backlog_counts["ordered"] = count
            elif status == StockStatusEnum.BACKORDER:
                backlog_counts["backorder"] = count

    completion_filters = [AuditLog.action == "status_change"]
    if created_from:
        completion_filters.append(AuditLog.created_at >= created_from)
    if created_to:
        completion_filters.append(AuditLog.created_at < created_to + timedelta(days=1))
    if job_ids:
        completion_filters.append(AuditLog.job_id.in_(job_ids))
    completed_in_range = (
        AuditLog.query.filter(*completion_filters)
        .filter(AuditLog.message.ilike("% to complete%"))
        .count()
    )

    wip_buckets = {"0-7": 0, "8-14": 0, "15-30": 0, "30+": 0}
    for job in active_jobs:
        created_at = _normalize_dt(job.created_at, now_norm)
        days = (now_norm - created_at).total_seconds() / 86400
        if days <= 7:
            wip_buckets["0-7"] += 1
        elif days <= 14:
            wip_buckets["8-14"] += 1
        elif days <= 30:
            wip_buckets["15-30"] += 1
        else:
            wip_buckets["30+"] += 1

    technicians = (
        User.query.filter(User.role == RoleEnum.TECHNICIAN)
        .order_by(User.username)
        .all()
    )
    engine_types = sorted(
        {et for (et,) in db.session.query(Job.engine_type).distinct().all() if et}
    )

    kpis = {
        "total_jobs": total_jobs,
        "jobs_by_status": jobs_by_status_dict,
        "average_job_age": average_job_age,
        "top_replaced_parts": top_replaced_parts,
        "avg_cycle_times": avg_cycle_times,
        "backlog_counts": backlog_counts,
        "active_jobs": len(active_jobs),
        "on_hold": sum(1 for job in jobs if job.status == JobStatusEnum.HOLD),
        "completed_in_range": completed_in_range,
        "wip_buckets": wip_buckets,
    }

    return render_template(
        "kpi_dashboard.html",
        kpis=kpis,
        filters={
            "created_from": request.args.get("created_from") or "",
            "created_to": request.args.get("created_to") or "",
            "engine_type": engine_type,
            "technician": tech_id,
        },
        technicians=technicians,
        engine_types=engine_types,
    )


@jobs_bp.route("/admin/system")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def system_status():
    db_ok = True
    db_message = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_message = str(exc)

    alembic_version = None
    try:
        alembic_version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        alembic_version = None

    recent_errors = (
        ErrorLog.query.order_by(ErrorLog.created_at.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "system_status.html",
        db_ok=db_ok,
        db_message=db_message,
        alembic_version=alembic_version,
        recent_errors=recent_errors,
    )
