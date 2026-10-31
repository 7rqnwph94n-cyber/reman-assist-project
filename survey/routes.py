import os
import re
from datetime import datetime, timezone
from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app,
    abort,
)
from sqlalchemy import func

from utils.pagination import parse_int_arg
from models import (
    db,
    Job,
    SurveyItem,
    PartRequirement,
    Template,
    TemplateItem,
    DecisionEnum,
    MeasurementResultEnum,
    JobStatusEnum,
    StockStatusEnum,
    RoleEnum,
    MeasurementAuditLog,
    InvalidJobTransition,
    TemplateSection,
    TemplateSectionIllustrationLink,
    IllustrationPage,
    IllustrationPartRow,
    IllustrationPosLabel,
    IllustrationHotspot,
)
from auth_utils import login_required, current_user, require_job_access, roles_required, job_access_required, get_org_filter, get_scoped_or_404
from services.job_services import change_job_status, ensure_survey_from_template, log_event
from utils.localization import t
from services.job_pack_revision import bump_revision
from services.measurement_service import apply_measurement_to_survey_item
from services.bom_services import apply_supersedes
from services.bom import regenerate_bom_for_job

survey_bp = Blueprint("survey", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)


def _build_section_images(job, upload_root):
    """Locate section images for the job/template."""
    section_images = {}

    template = job.template
    engine_type = template.engine_type if template and template.engine_type else None

    img_root = os.path.join(upload_root, "section_images")
    search_dirs = []

    if engine_type:
        # Sanitize engine_type to prevent path traversal (e.g. "../../etc")
        safe_engine = os.path.basename(engine_type.replace("\\", "/"))
        if safe_engine and safe_engine not in {".", ".."}:
            engine_dir = os.path.join(img_root, safe_engine)
            # Verify resolved path stays within img_root
            if os.path.realpath(engine_dir).startswith(os.path.realpath(img_root)):
                search_dirs.append(engine_dir)

    search_dirs.append(img_root)

    allowed_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue

        for fname in os.listdir(directory):
            base, ext = os.path.splitext(fname)
            if ext.lower() not in allowed_exts:
                continue

            clean = base.strip()
            core = clean.split("_", 1)[0].strip()

            code_no_space = core.replace(" ", "").upper()
            code_with_space = (
                f"{code_no_space[:2]} {code_no_space[2:]}"
                if len(code_no_space) > 3
                else code_no_space
            )

            pretty = clean.replace("_", " ")

            rel_path = os.path.relpath(os.path.join(directory, fname), upload_root)
            rel_path = rel_path.replace("\\", "/")
            img_url = url_for("uploaded_file", filename=rel_path)

            for key in {clean, core, code_no_space, code_with_space, pretty}:
                if key and key not in section_images:
                    section_images[key] = img_url

    return section_images


def _build_section_illustrations(job):
    if not job.template_id:
        return {}
    sections = (
        TemplateSection.query.filter_by(template_id=job.template_id)
        .order_by(TemplateSection.display_order, TemplateSection.id)
        .all()
    )
    section_map = {}
    for section in sections:
        links = (
            TemplateSectionIllustrationLink.query
            .filter_by(template_section_id=section.id)
            .order_by(TemplateSectionIllustrationLink.display_order, TemplateSectionIllustrationLink.id)
            .all()
        )
        published = []
        drafts = []
        for link in links:
            page = link.page
            if not page:
                continue
            title = (page.title or "").lower()
            image_name = (page.image_path or "").lower()
            if "cont" in title or "-cont" in image_name or "_cont" in image_name:
                continue
            parts = IllustrationPartRow.query.filter_by(illustration_page_id=page.id).all()
            labels = IllustrationPosLabel.query.filter_by(illustration_page_id=page.id).all()
            label_payload = [
                {"pos": lbl.pos, "x_norm": lbl.x_norm, "y_norm": lbl.y_norm}
                for lbl in labels
            ]
            hotspot_payload = [
                {"pos": hs.pos, "shape_json": hs.shape_json}
                for hs in IllustrationHotspot.query.filter_by(illustration_page_id=page.id).all()
            ]
            entry = (
                {
                    "page": page,
                    "image_url": url_for("uploaded_file", filename=page.image_path),
                    "parts": parts,
                    "labels": label_payload,
                    "hotspots": hotspot_payload,
                }
            )
            if page.status == "published":
                published.append(entry)
            else:
                drafts.append(entry)
        pages = published or drafts
        if pages:
            section_map[section.name] = pages
    return section_map


def _expand_section_illustrations(section_map: dict) -> dict:
    if not section_map:
        return {}
    expanded = {}
    for key, pages in section_map.items():
        clean = (key or "").strip()
        core = clean.split("_", 1)[0].strip()
        code_no_space = core.replace(" ", "").upper()
        code_with_space = (
            f"{code_no_space[:2]} {code_no_space[2:]}"
            if len(code_no_space) > 3
            else code_no_space
        )
        pretty = clean.replace("_", " ")
        normalized = _normalize_section_key(clean)
        stripped = _strip_prefix_variants(clean)
        leading_code = None
        match = re.match(r"^([A-Za-z]{1,4})\\s*-?\\s*(\\d{2,4})", clean)
        if match:
            leading_code = f"{match.group(1).upper()}{match.group(2)}"
        else:
            match = re.match(r"^(\\d{2}-\\d{4})", clean)
            if match:
                leading_code = match.group(1)
        leading_variants = []
        if leading_code:
            leading_variants.append(leading_code)
            leading_variants.append(
                f"{leading_code[:2]} {leading_code[2:]}" if len(leading_code) > 3 else leading_code
            )
        for variant in {clean, core, code_no_space, code_with_space, pretty, normalized, *stripped}:
            if variant and variant not in expanded:
                expanded[variant] = pages
        for variant in leading_variants:
            if variant and variant not in expanded:
                expanded[variant] = pages
    return expanded


def _normalize_section_key(value: str) -> str:
    if not value:
        return ""
    clean = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    for prefix in ("OEMPDF", "OEM", "PDF"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    return clean.strip()


def _strip_prefix_variants(value: str) -> list[str]:
    if not value:
        return []
    raw = value.strip()
    variants = []
    prefixes = [
        "OEM PDF ",
        "OEM-PDF ",
        "OEMPDF ",
        "OEM ",
        "PDF ",
    ]
    for prefix in prefixes:
        if raw.upper().startswith(prefix.strip().upper()):
            stripped = raw[len(prefix):].strip()
            if stripped:
                variants.append(stripped)
    return variants


def _expand_section_images_for_sections(section_images: dict, sections: list[str]) -> dict:
    if not section_images or not sections:
        return section_images
    normalized_map = {}
    for key, url in section_images.items():
        normalized = _normalize_section_key(key)
        if normalized and normalized not in normalized_map:
            normalized_map[normalized] = url
    for section_name in sections:
        clean = (section_name or "").strip()
        if not clean or clean in section_images:
            continue
        normalized = _normalize_section_key(clean)
        if normalized and normalized in normalized_map:
            section_images[clean] = normalized_map[normalized]
            continue
        for stripped in _strip_prefix_variants(clean):
            if stripped in section_images:
                section_images[clean] = section_images[stripped]
                break
        match = re.match(r"^([A-Za-z]{1,4})\\s*-?\\s*(\\d{2,4})", clean)
        code_variants = []
        if match:
            code = f"{match.group(1).upper()}{match.group(2)}"
            code_variants.append(code)
            code_variants.append(f"{code[:2]} {code[2:]}" if len(code) > 3 else code)
        else:
            match = re.match(r"^(\\d{2}-\\d{4})", clean)
            if match:
                code_variants.append(match.group(1))
        for variant in code_variants:
            if variant in section_images:
                section_images[clean] = section_images[variant]
                break
    return section_images




@survey_bp.route("/jobs/<int:job_id>/survey/seed", methods=["POST"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def seed_survey(job_id):
    job = _get_or_404(Job, job_id)
    ensure_survey_from_template(job)
    flash(f"{t('inspection_caps')} initialized from template.", "success")
    return redirect(url_for("survey.job_survey", job_id=job.id))


@survey_bp.route("/jobs/<int:job_id>/survey", methods=["GET", "POST"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.TECHNICIAN.value)
def job_survey(job_id):
    job = _get_or_404(Job, job_id)
    user = current_user()
    status_allows_edit = job.status in {JobStatusEnum.PRE_SURVEY, JobStatusEnum.SURVEY}
    read_only = bool(user and user.role in {RoleEnum.OFFICE, RoleEnum.STORES})
    if not status_allows_edit:
        read_only = True

    # ---- PRE-SURVEY GATE (DB-backed: requires PreSurveyResult row) ----
    pre_done = job.pre_survey_result is not None
    if not pre_done:
        flash(
            f"Please complete the {t('pre_inspection_lower')} check before starting the {t('strip_inspection_lower')}.",
            "info",
        )
        return redirect(url_for("jobs.job_pre_survey", job_id=job.id))
    # ---- END PRE-SURVEY GATE (DB-backed) ----
    if request.method == "GET" and job.status == JobStatusEnum.PRE_SURVEY:
        try:
            change_job_status(job, JobStatusEnum.SURVEY, user=current_user(), reason=f"{t('inspection_caps')} started")
        except InvalidJobTransition as exc:
            flash(str(exc), "danger")
            return redirect(url_for("jobs.job_detail", job_id=job.id))
        db.session.commit()

    layout = request.args.get("layout") or "classic"

    if request.method == "POST":
        if job.status == JobStatusEnum.COMPLETE:
            abort(403)
        ensure_survey_from_template(job)

    per_page = parse_int_arg("per_page", current_app.config.get("SURVEY_PAGE_SIZE", 100))
    per_page = max(1, min(per_page, current_app.config.get("SURVEY_PAGE_MAX", 200)))
    page = parse_int_arg("page", 1)
    if page < 1:
        page = 1

    base_query = SurveyItem.query.filter_by(job_id=job.id)
    total_items_all = base_query.count()

    if request.method == "GET" and total_items_all == 0 and job.template_id:
        section_images = _build_section_images(job, upload_root=current_app.config["UPLOAD_FOLDER"])
        section_illustrations = _expand_section_illustrations(_build_section_illustrations(job))
        return render_template(
            "job_survey.html",
            job=job,
            survey_items=[],
            DecisionEnum=DecisionEnum,
            layout=layout,
            section_images=section_images,
            section_illustrations=section_illustrations,
            read_only=True,
            sections=[],
            section_filter="",
            visible_ids=[],
            needs_seed=True,
            page=1,
            per_page=per_page,
            total_items=0,
            total_pages=1,
        )
    sections = []
    if total_items_all:
        sections = sorted({
            (sec or "General").strip() or "General"
            for (sec,) in db.session.query(SurveyItem.section)
            .filter_by(job_id=job.id)
            .distinct()
            .all()
        })
    section_filter = (request.args.get("section") or "").strip()
    if section_filter:
        section_filter = section_filter.strip()
    display_query = base_query
    if section_filter and section_filter.lower() != "all":
        display_query = display_query.filter(func.trim(SurveyItem.section) == section_filter)
    total_items = display_query.count()
    total_pages = max(1, (total_items + per_page - 1) // per_page) if total_items else 1
    if page > total_pages:
        page = total_pages

    display_items = (
        display_query
        .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    visible_ids = {si.id for si in display_items}

    section_images = _build_section_images(job, upload_root=current_app.config["UPLOAD_FOLDER"])
    section_images = _expand_section_images_for_sections(section_images, sections)
    section_illustrations = _expand_section_illustrations(_build_section_illustrations(job))

    if request.method == "POST":
        redirect_kwargs = {
            "job_id": job.id,
            "layout": layout,
            "page": page,
            "per_page": per_page,
        }
        if section_filter:
            redirect_kwargs["section"] = section_filter
        action = request.form.get("action", "save")
        if read_only:
            flash(t("inspection_read_only"), "warning")
            return redirect(url_for("survey.job_survey", **redirect_kwargs))
        if not status_allows_edit:
            flash(t("inspection_locked"), "danger")
            return redirect(url_for("survey.job_survey", **redirect_kwargs))
        try:
            expected_version = int(request.form.get("survey_version") or 0)
        except ValueError:
            expected_version = 0
        if expected_version != job.survey_version:
            if action == "autosave":
                return jsonify({"status": "conflict", "message": t("inspection_changed")}), 409
            flash(f"{t('inspection_changed')} Please reload and try again.", "danger")
            return redirect(url_for("survey.job_survey", job_id=job.id, layout=layout))

        # Hydrate missing measurement limits from template (for older jobs without seeded specs)
        if job.template_id:
            tmpl_items = (
                TemplateItem.query
                .filter_by(template_id=job.template_id)
                .all()
            )
            tmpl_map = {(ti.section, ti.pos, ti.part_no): ti for ti in tmpl_items}
            for item in display_items:
                if item.requires_measurement and (not item.spec_min or not item.spec_max or not item.measurement_unit):
                    tmpl_item = tmpl_map.get((item.section, item.pos, item.part_no))
                    if tmpl_item:
                        if not item.spec_min and tmpl_item.measurement_min is not None:
                            item.spec_min = str(tmpl_item.measurement_min)
                        if not item.spec_max and tmpl_item.measurement_max is not None:
                            item.spec_max = str(tmpl_item.measurement_max)
                        if not item.measurement_unit and tmpl_item.measurement_unit:
                            item.measurement_unit = tmpl_item.measurement_unit

        def _measurement_error(message: str):
            if action == "autosave":
                return jsonify({"status": "error", "message": message}), 400
            flash(message, "danger")
            return redirect(url_for("survey.job_survey", **redirect_kwargs))

        # 4a) Update decisions + notes for each existing row
        visible_ids_form = request.form.get("visible_ids") or ""
        try:
            visible_set = {
                int(v) for v in visible_ids_form.split(",") if v.strip().isdigit()
            }
        except ValueError:
            visible_set = set()
        # Constrain to items actually on this page to prevent hidden-item manipulation
        actual_page_ids = {si.id for si in display_items}
        if visible_set:
            visible_set = visible_set & actual_page_ids
        else:
            visible_set = actual_page_ids

        if visible_set:
            visible_items = (
                SurveyItem.query
                .filter(SurveyItem.job_id == job.id, SurveyItem.id.in_(visible_set))
                .all()
            )
        else:
            visible_items = []

        for item in visible_items:
            if item.id not in visible_set:
                continue
            decision_raw = request.form.get(f"decision_{item.id}", "").strip()
            if decision_raw:
                try:
                    item.decision = DecisionEnum(decision_raw)
                except ValueError:
                    item.decision = None
            else:
                item.decision = None

            notes_val = request.form.get(f"notes_{item.id}")
            if notes_val is not None:
                item.notes = notes_val.strip() or None

            if item.requires_measurement:
                old_torque_confirmed = item.torque_confirmed
                val_raw = (request.form.get(f"measurement_value_{item.id}") or "").strip()
                min_raw = (request.form.get(f"spec_min_{item.id}") or "").strip()
                max_raw = (request.form.get(f"spec_max_{item.id}") or "").strip()
                unit_raw = (request.form.get(f"measurement_unit_{item.id}") or "").strip()

                outcome = apply_measurement_to_survey_item(
                    item=item,
                    raw_value=val_raw,
                    spec_min=min_raw,
                    spec_max=max_raw,
                    unit=unit_raw,
                    label=item.name,
                    user=current_user(),
                )
                if outcome.get("error"):
                    return _measurement_error(outcome["error"])

                user = current_user()
                if old_torque_confirmed != item.torque_confirmed:
                    db.session.add(
                        MeasurementAuditLog(
                            survey_item_id=item.id,
                            user_id=user.id if user else None,
                            field_name="torque_confirmed",
                            old_value=str(old_torque_confirmed) if old_torque_confirmed is not None else None,
                            new_value=str(item.torque_confirmed) if item.torque_confirmed is not None else None,
                        )
                    )

            # Nonconformance workflow removed; survey drives BOM directly.

        # 4b) Add a new survey row if requested (skip during autosave to avoid duplicates)
        if action != "autosave":
            new_name = (request.form.get("new_name") or "").strip()
            if new_name:
                new_section = (request.form.get("new_section") or "").strip() or None
                new_pos_raw = (request.form.get("new_pos") or "").strip()
                new_pos = int(new_pos_raw) if new_pos_raw else None

                new_part_no = (request.form.get("new_part_no") or "").strip() or None
                if new_part_no:
                    new_part_no = new_part_no.upper()
                new_qty_raw = (request.form.get("new_qty") or "").strip()
                try:
                    new_qty = int(new_qty_raw) if new_qty_raw else 1
                except ValueError:
                    new_qty = 1

                db.session.add(
                    SurveyItem(
                        job_id=job.id,
                        section=new_section,
                        pos=new_pos,
                        part_no=new_part_no,
                        name=new_name,
                        qty=new_qty,
                    )
                )

        # 4c) If the tech hits "Complete", HARD-GATE completion until all
        # non-locked lines have a decision.
        if action == "complete":
            if not status_allows_edit:
                flash(f"{t('inspection_caps')} completion is locked once the job reaches Office/Build.", "danger")
                return redirect(url_for("survey.job_survey", job_id=job.id, layout=layout))
            undecided_count = (
                SurveyItem.query
                .filter(
                    SurveyItem.job_id == job.id,
                    SurveyItem.always_replace.is_(False),
                    SurveyItem.decision.is_(None),
                )
                .count()
            )

            if undecided_count:
                db.session.commit()
                flash(
                    f"Cannot complete {t('inspection')} – {undecided_count} line(s) still undecided.",
                    "error",
                )
                return redirect(url_for("survey.job_survey", **redirect_kwargs))

            missing_measurements_count = (
                SurveyItem.query
                .filter(
                    SurveyItem.job_id == job.id,
                    SurveyItem.requires_measurement.is_(True),
                    SurveyItem.measurement_result.in_(
                        [None, MeasurementResultEnum.NOT_MEASURED]
                    ),
                )
                .count()
            )
            if missing_measurements_count:
                db.session.commit()
                flash(
                    f"Cannot complete {t('inspection')} – {missing_measurements_count} measurement-required line(s) missing results.",
                    "error",
                )
                return redirect(url_for("survey.job_survey", **redirect_kwargs))

            if job.status in {JobStatusEnum.OFFICE, JobStatusEnum.BUILD, JobStatusEnum.COMPLETE}:
                flash("Survey already completed; no changes applied.", "warning")
                return redirect(url_for("survey.job_survey", **redirect_kwargs))

            created = 0
            try:
                all_items = (
                    base_query
                    .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
                    .all()
                )
                created = regenerate_bom_for_job(job, all_items, request.form)
                apply_supersedes(job.id)
                change_job_status(job, JobStatusEnum.OFFICE, user=None, reason=f"{t('inspection_caps')} completed")
                job.survey_version = (job.survey_version or 0) + 1
                log_event(
                    action="survey_completed",
                    message=f"{t('inspection_caps')} completed with {created} {t('parts_list_lines')}",
                    job=job,
                    user=current_user(),
                )
                bump_revision(job, "survey_completed/bom_generated", user=current_user())
                db.session.commit()
            except (InvalidJobTransition, Exception) as exc:
                db.session.rollback()
                flash(f"Survey completion failed; no changes applied. ({exc})", "danger")
                return redirect(url_for("survey.job_survey", **redirect_kwargs))

            if created > 0:
                flash(
                    f"{t('inspection_caps')} completed – {created} part line(s) added to the {t('parts_list')}.",
                    "success",
                )
            else:
                flash(
                    f"{t('inspection_caps')} completed – no parts required based on your decisions "
                    "(all items marked Good).",
                    "info",
                )

            return redirect(url_for("parts.job_parts", job_id=job.id))

        job.survey_version = (job.survey_version or 0) + 1
        if action != "autosave":
            log_event(
                action="survey_saved",
                message=t("inspection_updated"),
                job=job,
                user=current_user(),
            )
            if action != "complete":
                bump_revision(job, "survey_updated", user=current_user())
        db.session.commit()
        if action == "autosave":
            return jsonify({"status": "ok", "saved_at": datetime.utcnow().isoformat() + "Z"})
        flash(f"{t('strip_inspection')} updated.", "success")
        return redirect(url_for("survey.job_survey", **redirect_kwargs))

    return render_template(
        "job_survey.html",
        job=job,
        survey_items=display_items,
        DecisionEnum=DecisionEnum,
        layout=layout,
        section_images=section_images,
        section_illustrations=section_illustrations,
        read_only=read_only,
        sections=sections,
        section_filter=section_filter,
        visible_ids=sorted(visible_ids),
        page=page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
    )
