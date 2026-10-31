import pandas as pd
import os
import re
import math
import tempfile
import shutil
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
import json
from math import ceil
from werkzeug.utils import secure_filename

from models import db, Template, TemplateItem, TemplateGroup, TemplateSection, RoleEnum, Job, JobStatusEnum, CostingTemplateProfile, CostingTemplateLine, IllustrationPage, IllustrationPartRow, IllustrationPosLabel, IllustrationHotspot, TemplateSectionIllustrationLink, TemplateWizardState, TemplatePart, TemplateOccurrence, TemplateMeasurementSpec
from utils.localization import t
from services.measurement_service import normalize_decimal_field
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
    ALLOWED_COSTING_TEMPLATE_EXTENSIONS,
    ALLOWED_COSTING_TEMPLATE_MIME_TYPES,
)
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
from services.illustration_helpers import (
    _extract_rows_from_pdf_text,
    _extract_section_heading,
    _validate_parts,
    _find_legacy_section_image,
    _list_pdf_profiles,
    _normalize_section_key,
)

templates_bp = Blueprint("templates_bp", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)



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


def _extract_section_code_from_name(filename: str) -> str | None:
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    if not base:
        return None
    pretty = base.replace("_", " ").strip()
    matches = re.findall(r"[A-Za-z]{1,4}\s*\d{2,4}", pretty)
    if not matches:
        return None
    code = re.sub(r"\s+", "", matches[-1]).upper()
    return code or None


def _save_named_section_image(file_obj, target_dir: str) -> str | None:
    validate_upload(
        file_obj,
        allowed_exts=ALLOWED_IMAGE_EXTENSIONS,
        allowed_mimetypes=ALLOWED_IMAGE_MIME_TYPES,
        require_image=True,
    )
    filename = os.path.basename(file_obj.filename)
    if not filename:
        return None
    if re.search(r"\\bcont\\b", filename.lower()):
        return None
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    code = _extract_section_code_from_name(filename)
    if not code:
        return None
    os.makedirs(target_dir, exist_ok=True)
    base_name = f"{code}{ext}"
    out_path = os.path.join(target_dir, base_name)
    if os.path.exists(out_path):
        counter = 2
        while True:
            candidate = f"{code}-{counter}{ext}"
            out_path = os.path.join(target_dir, candidate)
            if not os.path.exists(out_path):
                break
            counter += 1
    file_obj.save(out_path)
    return os.path.relpath(out_path, current_app.config["UPLOAD_FOLDER"])


def _build_section_images_for_template(template: Template, upload_root: str) -> dict[str, str]:
    section_images: dict[str, str] = {}
    engine_type = template.engine_type if template and template.engine_type else None
    img_root = os.path.join(upload_root, "section_images")
    search_dirs = []
    if engine_type:
        search_dirs.append(os.path.join(img_root, engine_type))
    search_dirs.append(os.path.join(img_root, "generic"))
    if os.path.isdir(img_root):
        for entry in os.listdir(img_root):
            cand = os.path.join(img_root, entry)
            if os.path.isdir(cand):
                search_dirs.append(cand)
    search_dirs.append(img_root)
    allowed_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

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
            core = clean.split("_", 1)[0].strip()
            code_no_space = core.replace(" ", "").upper()
            code_with_space = (
                f"{code_no_space[:2]} {code_no_space[2:]}"
                if len(code_no_space) > 3
                else code_no_space
            )
            pretty = clean.replace("_", " ")
            code_candidates = set()
            for match in re.findall(r"[A-Za-z]{1,4}\s*\d{2,4}", pretty):
                code = re.sub(r"\s+", "", match).upper()
                code_candidates.add(code)
                if len(code) > 3:
                    code_candidates.add(f"{code[:2]} {code[2:]}")
            rel_path = os.path.relpath(os.path.join(directory, fname), upload_root).replace("\\", "/")
            img_url = url_for("uploaded_file", filename=rel_path)
            keys = {
                clean,
                core,
                code_no_space,
                code_with_space,
                pretty,
                _normalize_section_key(clean),
                _normalize_section_key(pretty),
            }
            keys.update(code_candidates)
            for variant in _strip_prefix_variants(pretty):
                keys.add(variant)
                keys.add(_normalize_section_key(variant))
            for key in keys:
                if key and key not in section_images:
                    section_images[key] = img_url

    return section_images


def _expand_section_images_for_sections(section_images: dict[str, str], sections) -> dict[str, str]:
    expanded = dict(section_images)
    normalized_map = { _normalize_section_key(k): v for k, v in section_images.items() if k }
    for sec in sections:
        name = (getattr(sec, "name", sec) or "").strip()
        if not name:
            continue
        if name in expanded:
            continue
        normalized = _normalize_section_key(name)
        if normalized and normalized in normalized_map:
            expanded[name] = normalized_map[normalized]
            continue
        for variant in _strip_prefix_variants(name):
            if variant in expanded:
                expanded[name] = expanded[variant]
                break
            vnorm = _normalize_section_key(variant)
            if vnorm and vnorm in normalized_map:
                expanded[name] = normalized_map[vnorm]
                break
        if name in expanded:
            continue
        match = re.match(r"^([A-Za-z]{1,4})\s*-?\s*(\d{2,4})", name)
        if match:
            code = f"{match.group(1).upper()}{match.group(2)}"
            if code in expanded:
                expanded[name] = expanded[code]
                continue
            spaced = f"{code[:2]} {code[2:]}" if len(code) > 3 else code
            if spaced in expanded:
                expanded[name] = expanded[spaced]
    return expanded


@templates_bp.route("/admin/templates")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def templates_list():
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    per_page = current_app.config.get("TEMPLATES_PAGE_SIZE", 50)
    per_page = max(1, min(per_page, current_app.config.get("TEMPLATES_PAGE_MAX", 200)))

    org_id = get_org_filter()
    q = Template.query.filter(Template.organization_id == org_id).order_by(Template.name)
    total = q.count()
    total_pages = max(1, ceil(total / per_page)) if total else 1
    if page > total_pages:
        page = total_pages
    templates = q.offset((page - 1) * per_page).limit(per_page).all()
    return render_template(
        "templates_list.html",
        templates=templates,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total=total,
    )


@templates_bp.route("/admin/templates/create", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        engine_type = request.form.get("engine_type", "").strip()
        org_id = get_org_filter()

        if not name:
            flash("Template name is required.", "danger")
            return redirect(url_for("templates_bp.template_create"))

        if Template.query.filter_by(name=name, organization_id=org_id).first():
            flash("A template with that name already exists.", "danger")
            return redirect(url_for("templates_bp.template_create"))

        user = current_user()
        template = Template(
            name=name,
            engine_type=engine_type or None,
            organization_id=org_id,
        )
        db.session.add(template)
        db.session.commit()
        flash("Template created.", "success")
        return redirect(url_for("templates_bp.templates_list"))

    return render_template("template_create.html")


def _load_presurvey(template: Template):
    try:
        data = json.loads(template.pre_survey_schema) if template.pre_survey_schema else []
        if not isinstance(data, list):
            return []
        # normalise
        out = []
        for field in data:
            label = (field.get("label") or "").strip()
            ftype = (field.get("type") or "checkbox").strip()
            opts = field.get("options") or ""
            out.append({"label": label, "type": ftype, "options": opts})
        return out
    except Exception:
        return []


def _save_presurvey(template: Template, fields):
    template.pre_survey_schema = json.dumps(fields)
    db.session.add(template)
    db.session.commit()


@templates_bp.route("/admin/templates/<int:template_id>/presurvey", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_presurvey(template_id):
    template = _get_or_404(Template, template_id)
    fields = _load_presurvey(template)

    if request.method == "POST":
        new_fields = []
        # Existing rows keyed by index
        for idx in range(1, len(fields) + 1):
            label = (request.form.get(f"label_{idx}") or "").strip()
            ftype = (request.form.get(f"type_{idx}") or "checkbox").strip()
            opts = (request.form.get(f"options_{idx}") or "").strip()
            if not label:
                continue
            new_fields.append({"label": label, "type": ftype, "options": opts})

        new_label = (request.form.get("new_label") or "").strip()
        if new_label:
            new_type = (request.form.get("new_type") or "checkbox").strip()
            new_opts = (request.form.get("new_options") or "").strip()
            new_fields.append({"label": new_label, "type": new_type, "options": new_opts})

        _save_presurvey(template, new_fields)
        flash(f"{t('pre_inspection')} saved.", "success")
        return redirect(url_for("templates_bp.template_presurvey", template_id=template.id))

    return render_template(
        "template_presurvey.html",
        template=template,
        presurvey_fields=fields,
    )


@templates_bp.route("/admin/templates/<int:template_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_edit(template_id):
    template = _get_or_404(Template, template_id)

    items = (
        TemplateItem.query.filter_by(template_id=template.id)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )
    section_names = []
    for item in items:
        name = (item.section or "General").strip() or "General"
        if name not in section_names:
            section_names.append(name)
    existing_sections = {
        s.name: s
        for s in TemplateSection.query.filter_by(template_id=template.id).all()
    }
    section_id_map = {}
    for idx, name in enumerate(section_names, start=1):
        sec = existing_sections.get(name)
        if not sec:
            sec = TemplateSection(template_id=template.id, name=name, display_order=idx)
            db.session.add(sec)
            db.session.flush()
        else:
            if sec.display_order != idx:
                sec.display_order = idx
        section_id_map[name] = sec.id
    db.session.commit()

    template_groups = (
        TemplateGroup.query.filter_by(template_id=template.id)
        .order_by(TemplateGroup.label)
        .all()
    )

    if (
        request.method == "POST"
        and request.form.get("action") == "import_sheet"
        and not template.is_locked
    ):
        uploaded = request.files.get("file")
        if not uploaded or uploaded.filename == "":
            flash("No file selected for import.", "danger")
            return redirect(url_for("templates_bp.template_edit", template_id=template.id))

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        name = (request.form.get("name") or "").strip()
        engine_type = (request.form.get("engine_type") or "").strip()
        locked_flag = request.form.get("locked")
        new_group_label = (request.form.get("new_group_label") or "").strip()
        dirty = False

        if name:
            template.name = name
        template.engine_type = engine_type or None
        template.is_locked = bool(locked_flag)

        if new_group_label and (not getattr(template, "is_locked", False)):
            safe = "".join(
                ch.lower() if ch.isalnum() else "_" for ch in new_group_label
            ).strip("_") or "kit"
            base_code = safe[:32]
            code = base_code
            counter = 1
            while TemplateGroup.query.filter_by(template_id=template.id, code=code).first() is not None:
                counter += 1
                code = f"{base_code}_{counter}"
            existing = TemplateGroup.query.filter_by(
                template_id=template.id, label=new_group_label
            ).first()
            if not existing:
                new_group = TemplateGroup(
                    template_id=template.id,
                    code=code,
                    label=new_group_label,
                    type="other",
                )
                db.session.add(new_group)

        items = (
            TemplateItem.query.filter_by(template_id=template.id)
            .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
            .all()
        )

        for item in items:
            if template.is_locked:
                break
            item.section = request.form.get(f"section_{item.id}") or ""
            pos_val = request.form.get(f"pos_{item.id}")
            try:
                item.pos = int(pos_val) if pos_val else None
            except ValueError:
                item.pos = None

            item.part_no = request.form.get(f"part_no_{item.id}") or ""
            item.name = request.form.get(f"name_{item.id}") or ""
            qty_val = request.form.get(f"qty_{item.id}")
            try:
                item.qty = int(qty_val) if qty_val else 1
            except ValueError:
                item.qty = 1

            item.always_replace = bool(request.form.get(f"always_replace_{item.id}"))
            item.in_kit = bool(request.form.get(f"in_kit_{item.id}"))
            item.big_ticket = bool(request.form.get(f"big_ticket_{item.id}"))
            item.requires_test = bool(request.form.get(f"requires_test_{item.id}"))
            item.requires_measurement = bool(
                request.form.get(f"requires_measurement_{item.id}")
            )

            item.measurement_label = (
                request.form.get(f"measurement_label_{item.id}") or None
            )
            item.measurement_unit = (
                request.form.get(f"measurement_unit_{item.id}") or None
            )

            min_val = request.form.get(f"measurement_min_{item.id}")
            max_val = request.form.get(f"measurement_max_{item.id}")
            try:
                min_dec, _ = normalize_decimal_field(min_val)
                item.measurement_min = float(min_dec) if min_dec is not None else None
            except ValueError:
                item.measurement_min = None
            try:
                max_dec, _ = normalize_decimal_field(max_val)
                item.measurement_max = float(max_dec) if max_dec is not None else None
            except ValueError:
                item.measurement_max = None

            if f"supersedes_{item.id}" in request.form:
                supersedes_raw = request.form.get(f"supersedes_{item.id}") or ""
                item.supersedes = supersedes_raw.strip() or None
            if f"bundles_{item.id}" in request.form:
                bundles_raw = request.form.get(f"bundles_{item.id}") or ""
                item.bundles = bundles_raw.strip() or None

            group_val = request.form.get(f"group_{item.id}") or ""
            if group_val:
                try:
                    grp_id = int(group_val)
                except ValueError:
                    grp_id = None
                grp = TemplateGroup.query.filter_by(id=grp_id, template_id=template.id).first() if grp_id else None
                if grp:
                    item.groups = [grp]
                else:
                    item.groups = []
            else:
                item.groups = []
            dirty = True

        if action == "add_row" and not template.is_locked:
            new_section = request.form.get("new_section") or ""
            new_pos = request.form.get("new_pos")
            new_part_no = request.form.get("new_part_no") or ""
            new_name = request.form.get("new_name") or ""
            new_qty = request.form.get("new_qty")

            try:
                new_pos_int = int(new_pos) if new_pos else None
            except ValueError:
                new_pos_int = None

            try:
                new_qty_int = int(new_qty) if new_qty else 1
            except ValueError:
                new_qty_int = 1

            new_item = TemplateItem(
                template_id=template.id,
                organization_id=template.organization_id,
                section=new_section,
                pos=new_pos_int,
                part_no=new_part_no,
                name=new_name,
                qty=new_qty_int,
                always_replace=bool(request.form.get("new_always_replace")),
                in_kit=bool(request.form.get("new_in_kit")),
                big_ticket=bool(request.form.get("new_big_ticket")),
                requires_test=bool(request.form.get("new_requires_test")),
                supersedes=(request.form.get("new_supersedes") or "").strip() or None,
                bundles=(request.form.get("new_bundles") or "").strip() or None,
            )
            db.session.add(new_item)
            dirty = True

        if dirty:
            template.version = (template.version or 0) + 1

        db.session.commit()
        flash("Template updated.", "success")

        return_to_wizard = request.form.get("return_to_wizard") == "1"
        return_step = request.form.get("return_step") or "2"
        if return_to_wizard:
            wizard = TemplateWizardState.query.filter_by(template_id=template.id).first()
            if wizard:
                step_status = wizard.step_status or {}
                step_status["step2"] = {
                    "complete": True,
                    "errors": [],
                    "warnings": [],
                }
                wizard.step_status = step_status
                wizard.current_step = max(wizard.current_step or 1, 2)
                flag_modified(wizard, "step_status")
                db.session.add(wizard)
                db.session.commit()
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step=return_step))

        if action == "add_row":
            return redirect(url_for("templates_bp.template_edit", template_id=template.id))
        return redirect(url_for("templates_bp.template_edit", template_id=template.id))

    ordered_sections = (
        TemplateSection.query
        .filter_by(template_id=template.id)
        .order_by(TemplateSection.display_order, TemplateSection.id)
        .all()
    )
    section_images = _build_section_images_for_template(template, current_app.config["UPLOAD_FOLDER"])
    section_images = _expand_section_images_for_sections(section_images, ordered_sections)
    section_names = []
    for item in items:
        name = (item.section or "General").strip() or "General"
        if name not in section_names:
            section_names.append(name)
    section_images = _expand_section_images_for_sections(section_images, section_names)
    for name in section_names:
        if name in section_images:
            continue
        rel_path = _find_legacy_section_image(template, name)
        if rel_path:
            section_images[name] = url_for("uploaded_file", filename=rel_path)
    section_images = _expand_section_images_for_sections(section_images, ordered_sections)
    section_images = _expand_section_images_for_sections(section_images, ordered_sections)
    section_images = _expand_section_images_for_sections(section_images, ordered_sections)
    illustrations_by_section = {}
    for sec in TemplateSection.query.filter_by(template_id=template.id).all():
        link = (
            TemplateSectionIllustrationLink.query
            .filter_by(template_section_id=sec.id)
            .order_by(TemplateSectionIllustrationLink.display_order, TemplateSectionIllustrationLink.id)
            .first()
        )
        if link and link.page and link.page.image_path:
            illustrations_by_section[sec.name] = url_for("uploaded_file", filename=link.page.image_path)

    return render_template(
        "template_edit.html",
        template=template,
        items=items,
        template_groups=template_groups,
        enable_template_costing=current_app.config.get("ENABLE_TEMPLATE_COSTING", False),
        enable_template_wizard=current_app.config.get("ENABLE_TEMPLATE_WIZARD", False),
        section_id_map=section_id_map,
        section_images=section_images,
        illustrations_by_section=illustrations_by_section,
    )


@templates_bp.route("/admin/templates/<int:template_id>/wizard", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_wizard(template_id):
    template = _get_or_404(Template, template_id)
    wizard = TemplateWizardState.query.filter_by(template_id=template.id).first()
    if not wizard:
        wizard = TemplateWizardState(template_id=template.id, status="draft", current_step=1)
        db.session.add(wizard)
        db.session.commit()

    step = (request.args.get("step") or "1").strip()
    step_status = wizard.step_status or {}
    step_data = wizard.step_data or {}
    def _normalize_part_no(part_no: str) -> str:
        return "".join(ch for ch in (part_no or "").upper().strip() if ch.isalnum() or ch in {".", "-", "/"})

    def _build_canonical_from_items() -> dict:
        TemplateOccurrence.query.filter_by(template_id=template.id).delete()
        TemplatePart.query.filter_by(template_id=template.id).delete()
        db.session.flush()

        items = (
            TemplateItem.query.filter_by(template_id=template.id)
            .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
            .all()
        )
        part_map = {}
        missing_part_no = 0
        occurrences = 0
        for item in items:
            if not item.part_no:
                missing_part_no += 1
                continue
            norm = _normalize_part_no(item.part_no)
            if not norm:
                missing_part_no += 1
                continue
            part = part_map.get(norm)
            if not part:
                part = TemplatePart(
                    template_id=template.id,
                    part_no=item.part_no,
                    normalized_part_no=norm,
                    name=item.name,
                )
                db.session.add(part)
                db.session.flush()
                part_map[norm] = part

            db.session.add(
                TemplateOccurrence(
                    template_id=template.id,
                    template_part_id=part.id,
                    template_item_id=item.id,
                    section=item.section,
                    pos=item.pos,
                    qty=item.qty or 1,
                )
            )
            occurrences += 1

        db.session.commit()
        return {
            "parts": len(part_map),
            "occurrences": occurrences,
            "skipped": missing_part_no,
        }

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "save_step1":
            name = (request.form.get("name") or "").strip()
            engine_type = (request.form.get("engine_type") or "").strip()
            sections_text = (request.form.get("sections") or "").strip()
            sections = [line.strip() for line in sections_text.splitlines() if line.strip()]

            errors = []
            warnings = []
            if not name:
                errors.append("Template name is required.")
            else:
                existing = Template.query.filter(
                    Template.name == name,
                    Template.id != template.id,
                    Template.organization_id == template.organization_id,
                ).first()
                if existing:
                    errors.append("Template name must be unique.")
            if not sections:
                errors.append("At least one section is required.")

            if errors:
                for err in errors:
                    flash(err, "danger")
            else:
                template.name = name
                template.engine_type = engine_type or None
                db.session.add(template)

                existing_sections = {
                    s.name: s
                    for s in TemplateSection.query.filter_by(template_id=template.id).all()
                }
                for idx, section_name in enumerate(sections, start=1):
                    sec = existing_sections.get(section_name)
                    if not sec:
                        sec = TemplateSection(
                            template_id=template.id,
                            name=section_name,
                            display_order=idx,
                        )
                        db.session.add(sec)
                    else:
                        sec.display_order = idx
                extra_sections = set(existing_sections.keys()) - set(sections)
                if extra_sections:
                    warnings.append(
                        f"{len(extra_sections)} existing section(s) not in the list were left unchanged."
                    )

                step_status["step1"] = {
                    "complete": True,
                    "errors": [],
                    "warnings": warnings,
                }
                step_data["step1"] = {
                    "name": name,
                    "engine_type": engine_type,
                    "sections": sections,
                }
                wizard.step_status = step_status
                wizard.step_data = step_data
                wizard.current_step = 1
                db.session.add(wizard)
                db.session.commit()
                flash("Step 1 saved.", "success")
                for warn in warnings:
                    flash(warn, "warning")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))
        if action == "wizard_import_csv" and not template.is_locked:
            uploaded = request.files.get("file")
            replace_existing = bool(request.form.get("replace_existing"))
            if not uploaded or uploaded.filename == "":
                flash("No file selected for import.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            try:
                validate_upload(
                    uploaded,
                    allowed_exts=ALLOWED_TEMPLATE_IMPORT_EXTENSIONS,
                    allowed_mimetypes=ALLOWED_TEMPLATE_IMPORT_MIME_TYPES,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            filename = uploaded.filename.lower()
            try:
                if filename.endswith(".csv"):
                    df = pd.read_csv(uploaded)
                else:
                    df = pd.read_excel(uploaded)
            except Exception as exc:
                flash(f"Could not read file: {exc}", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            df.columns = [c.strip().lower() for c in df.columns]

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

            col_section = col("section", "section code", "section_name")
            col_pos = col("pos", "position", "item", "item no")
            col_part = col("part_no", "part no", "partno", "part number", "partnumber", "part")
            col_name = col("name", "description", "desc", "part name", "item description")
            col_qty = col("qty", "quantity", "qty req", "qty required")

            if col_section is None or col_part is None or col_name is None:
                flash(
                    "Import failed: file must contain at least Section, Part No, and Name columns.",
                    "danger",
                )
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            if replace_existing:
                TemplateItem.query.filter_by(template_id=template.id).delete()
                db.session.flush()

            created = 0
            for idx in range(len(df)):
                section = str(col_section.iloc[idx]) if not pd.isna(col_section.iloc[idx]) else ""
                part_no = str(col_part.iloc[idx]) if not pd.isna(col_part.iloc[idx]) else ""
                name = str(col_name.iloc[idx]) if not pd.isna(col_name.iloc[idx]) else ""

                if not part_no and not name:
                    continue

                pos_val = None
                if col_pos is not None and not pd.isna(col_pos.iloc[idx]):
                    try:
                        pos_val = int(col_pos.iloc[idx])
                    except (ValueError, TypeError):
                        pos_val = None

                qty_val = 1
                if col_qty is not None and not pd.isna(col_qty.iloc[idx]):
                    try:
                        qty_val = int(col_qty.iloc[idx])
                    except (ValueError, TypeError):
                        qty_val = 1

                db.session.add(
                    TemplateItem(
                        template_id=template.id,
                        organization_id=template.organization_id,
                        section=section,
                        pos=pos_val,
                        part_no=part_no,
                        name=name,
                        qty=qty_val,
                    )
                )
                created += 1

            template.version = (template.version or 0) + 1
            db.session.commit()

            summary = _build_canonical_from_items()
            step_status["step1"] = {
                "complete": True,
                "errors": [],
                "warnings": [f"{summary['skipped']} rows missing part numbers were skipped."] if summary["skipped"] else [],
                "summary": {
                    "rows_created": created,
                    "replace_existing": replace_existing,
                    "canonical_parts": summary["parts"],
                    "occurrences": summary["occurrences"],
                },
            }
            wizard.step_status = step_status
            wizard.step_data = step_data
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash(f"Imported {created} template rows from CSV.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

        if action == "wizard_import_pdf" and not template.is_locked:
            uploaded = request.files.get("pdf_file")
            replace_existing = True
            profile = (request.form.get("pdf_profile") or "auto").strip() or "auto"
            confirm_wipe = bool(request.form.get("confirm_wipe"))
            confirm_text = (request.form.get("wipe_confirm_text") or "").strip().upper()
            if not uploaded or uploaded.filename == "":
                flash("No PDF selected for import.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))
            if not confirm_wipe or confirm_text != "WIPE":
                flash("PDF import requires explicit WIPE confirmation.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            active_jobs_count = Job.query.filter(
                Job.template_id == template.id,
                Job.status != JobStatusEnum.COMPLETE,
            ).count()
            if active_jobs_count:
                flash(
                    f"PDF wipe blocked: {active_jobs_count} active job(s) use this template.",
                    "danger",
                )
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            try:
                validate_upload(
                    uploaded,
                    allowed_exts=ALLOWED_PDF_EXTENSIONS,
                    allowed_mimetypes=ALLOWED_PDF_MIME_TYPES,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            try:
                from pdf_parts_extractor.extract import run_extract  # type: ignore
                from pdf_parts_extractor.profiles import list_profiles  # type: ignore
            except Exception as exc:
                flash(
                    f"PDF extractor not available. Run scripts/check_pdf_extractor.sh and fix any errors. ({exc})",
                    "danger",
                )
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            warnings = []
            profiles = [os.path.basename(p) for p in list_profiles() or []]
            if profile != "auto" and profile not in profiles:
                flash(f"Profile not found: {profile}", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            tmp_dir = tempfile.mkdtemp(prefix="pdf_extract_")
            keep_tmp = request.form.get("pdf_debug") == "1"
            created_files = []
            success = False
            try:
                pdf_name = secure_filename(uploaded.filename) or "upload.pdf"
                pdf_path = os.path.join(tmp_dir, pdf_name)
                uploaded.save(pdf_path)

                out_dir = os.path.join(tmp_dir, "out")
                os.makedirs(out_dir, exist_ok=True)
                try:
                    run_extract(pdf_path, out_dir, profile, debug=False)
                except Exception as exc:
                    flash(f"PDF extractor failed: {exc}", "danger")
                    return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

                parts_csv_path = os.path.join(out_dir, "parts.csv")
                if not os.path.exists(parts_csv_path):
                    flash("PDF extractor did not produce parts.csv.", "danger")
                    return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

                try:
                    df = pd.read_csv(parts_csv_path)
                except Exception as exc:
                    flash(f"Could not read parts.csv: {exc}", "danger")
                    return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

                df.columns = [c.strip().lower() for c in df.columns]

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

                col_section = col("section", "section code", "section_name", "section name", "assembly", "group")
                col_group = col("group_id", "group id", "group")
                col_pos = col("pos", "position", "item", "item no", "item_no")
                col_part = col("part_no", "part no", "partno", "part number", "partnumber", "part")
                col_name = col("name", "description", "desc", "part name", "item description", "designation")
                col_qty = col("qty", "quantity", "qty req", "qty required")

                if col_part is None and col_name is None:
                    flash("Import failed: parts.csv must include a Part No or Description column.", "danger")
                    return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))
                if col_section is None and col_group is None:
                    warnings.append("No Section column found. Using 'General' for all rows.")

                created = 0
                ordered_sections = []
                items_to_add = []
                group_to_section = {}
                group_to_section_norm = {}
                def _norm_section(val):
                    return re.sub(r"[^A-Za-z0-9]+", "", val or "").upper()
                for idx in range(len(df)):
                    section_val = ""
                    if col_section is not None and not pd.isna(col_section.iloc[idx]):
                        section_val = str(col_section.iloc[idx]).strip()
                    group_val = ""
                    if col_group is not None and not pd.isna(col_group.iloc[idx]):
                        group_val = str(col_group.iloc[idx]).strip()
                    if not section_val and group_val:
                        section_val = group_val
                    section = section_val or "General"
                    if section not in ordered_sections:
                        ordered_sections.append(section)
                    if group_val and section_val:
                        group_to_section.setdefault(group_val, section_val)
                        norm_group = _norm_section(group_val)
                        if norm_group:
                            group_to_section_norm.setdefault(norm_group, section_val)

                    part_no = ""
                    if col_part is not None and not pd.isna(col_part.iloc[idx]):
                        part_no = str(col_part.iloc[idx]).strip()
                    name = ""
                    if col_name is not None and not pd.isna(col_name.iloc[idx]):
                        name = str(col_name.iloc[idx]).strip()

                    if not part_no and not name:
                        continue

                    pos_val = None
                    if col_pos is not None and not pd.isna(col_pos.iloc[idx]):
                        try:
                            pos_val = int(col_pos.iloc[idx])
                        except (ValueError, TypeError):
                            pos_val = None

                    qty_val = 1
                    if col_qty is not None and not pd.isna(col_qty.iloc[idx]):
                        try:
                            qty_val = int(col_qty.iloc[idx])
                        except (ValueError, TypeError):
                            qty_val = 1
                    items_to_add.append(
                        {
                            "section": section,
                            "pos": pos_val,
                            "part_no": part_no or None,
                            "name": name or None,
                            "qty": qty_val,
                        }
                    )
                    created += 1

                images_root = os.path.join(out_dir, "images")
                total_images = 0
                matched_images = 0
                sample_groups = set()

                with db.session.begin_nested():
                    if replace_existing:
                        TemplateItem.query.filter_by(template_id=template.id).delete()
                        db.session.flush()

                    existing_sections = {
                        s.name: s
                        for s in TemplateSection.query.filter_by(template_id=template.id).all()
                    }
                    for idx, section_name in enumerate(ordered_sections, start=1):
                        sec = existing_sections.get(section_name)
                        if not sec:
                            sec = TemplateSection(
                                template_id=template.id,
                                name=section_name,
                                display_order=idx,
                            )
                            db.session.add(sec)
                        else:
                            sec.display_order = idx
                    extra_sections = set(existing_sections.keys()) - set(ordered_sections)
                    if extra_sections:
                        warnings.append(
                            f"{len(extra_sections)} existing section(s) not in the PDF were left unchanged."
                        )

                    for item in items_to_add:
                        db.session.add(
                            TemplateItem(
                                template_id=template.id,
                                organization_id=template.organization_id,
                                section=item["section"],
                                pos=item["pos"],
                                part_no=item["part_no"],
                                name=item["name"],
                                qty=item["qty"],
                            )
                        )

                    if replace_existing:
                        section_ids = [s.id for s in existing_sections.values()]
                        if section_ids:
                            page_ids = [
                                link.illustration_page_id
                                for link in TemplateSectionIllustrationLink.query.filter(
                                    TemplateSectionIllustrationLink.template_section_id.in_(section_ids)
                                ).all()
                            ]
                            if page_ids:
                                IllustrationPartRow.query.filter(
                                    IllustrationPartRow.illustration_page_id.in_(page_ids)
                                ).delete(synchronize_session=False)
                                IllustrationPosLabel.query.filter(
                                    IllustrationPosLabel.illustration_page_id.in_(page_ids)
                                ).delete(synchronize_session=False)
                                IllustrationHotspot.query.filter(
                                    IllustrationHotspot.illustration_page_id.in_(page_ids)
                                ).delete(synchronize_session=False)
                                TemplateSectionIllustrationLink.query.filter(
                                    TemplateSectionIllustrationLink.illustration_page_id.in_(page_ids)
                                ).delete(synchronize_session=False)
                                IllustrationPage.query.filter(
                                    IllustrationPage.id.in_(page_ids)
                                ).delete(synchronize_session=False)

                    section_map = {
                        s.name: s
                        for s in TemplateSection.query.filter_by(template_id=template.id).all()
                    }
                    section_map_norm = {_norm_section(name): sec for name, sec in section_map.items()}
                    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
                    order_by_section = {}
                    if os.path.isdir(images_root):
                        for dirpath, _dirnames, filenames in os.walk(images_root):
                            for fname in filenames:
                                ext = os.path.splitext(fname)[1].lower()
                                if ext not in image_exts:
                                    continue
                                total_images += 1
                                base = os.path.splitext(fname)[0]
                                match = re.match(r"(.+?)_diagram_p\d+", base)
                                if not match:
                                    continue
                                group_id = match.group(1)
                                if len(sample_groups) < 5:
                                    sample_groups.add(group_id)
                                section_obj = section_map.get(group_id)
                                if not section_obj:
                                    mapped = group_to_section.get(group_id)
                                    if not mapped:
                                        mapped = group_to_section_norm.get(_norm_section(group_id))
                                    if mapped:
                                        section_obj = section_map.get(mapped) or section_map_norm.get(_norm_section(mapped))
                                if not section_obj:
                                    section_obj = section_map_norm.get(_norm_section(group_id))
                                if not section_obj and section_map_norm:
                                    norm_group = _norm_section(group_id)
                                    for norm_name, sec in section_map_norm.items():
                                        if norm_group and (norm_group in norm_name or norm_name in norm_group):
                                            section_obj = sec
                                            break
                                if not section_obj:
                                    continue
                                matched_images += 1
                                src_path = os.path.join(dirpath, fname)
                                dest_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], f"illustrations/{template.id}")
                                os.makedirs(dest_dir, exist_ok=True)
                                safe_section = secure_filename(section_obj.name) or "section"
                                dest_name = f"{safe_section}_{uuid.uuid4().hex}_{fname}"
                                dest_path = os.path.join(dest_dir, dest_name)
                                created_files.append(dest_path)
                                try:
                                    shutil.copyfile(src_path, dest_path)
                                except Exception as exc:
                                    flash(f"Failed to copy extracted illustration file: {exc}", "danger")
                                    return redirect(
                                        url_for(
                                            "templates_bp.template_wizard",
                                            template_id=template.id,
                                            step="1",
                                        )
                                    )
                                rel_path = os.path.relpath(dest_path, current_app.config["UPLOAD_FOLDER"])
                                page = IllustrationPage(
                                    title=f"{group_id} diagram",
                                    image_path=rel_path,
                                    status="draft",
                                    created_by_id=current_user().id if current_user() else None,
                                )
                                db.session.add(page)
                                db.session.flush()
                                display_order = order_by_section.get(section_obj.id, 0) + 1
                                order_by_section[section_obj.id] = display_order
                                db.session.add(
                                    TemplateSectionIllustrationLink(
                                        template_section_id=section_obj.id,
                                        illustration_page_id=page.id,
                                        display_order=display_order,
                                    )
                                )
                    template.version = (template.version or 0) + 1
                success = True
            finally:
                if not success:
                    for path in created_files:
                        try:
                            if os.path.exists(path):
                                os.remove(path)
                        except OSError:
                            pass
                if keep_tmp:
                    flash(f"PDF extractor temp kept at {tmp_dir}", "warning")
                else:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

            summary = _build_canonical_from_items()
            if total_images == 0:
                warnings.append("No images were extracted from the PDF.")
            elif matched_images == 0:
                group_hint = ", ".join(sorted(sample_groups)) if sample_groups else "unknown"
                warnings.append(f"Images extracted but none matched sections. Example groups: {group_hint}")
            step_status["step1"] = {
                "complete": True,
                "errors": [],
                "warnings": warnings + (
                    [f"{summary['skipped']} rows missing part numbers were skipped."] if summary["skipped"] else []
                ),
                "summary": {
                    "rows_created": created,
                    "replace_existing": replace_existing,
                    "canonical_parts": summary["parts"],
                    "occurrences": summary["occurrences"],
                },
            }
            wizard.step_status = step_status
            wizard.step_data = step_data
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash(f"Imported {created} template rows from PDF.", "success")
            for warn in warnings:
                flash(warn, "warning")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

        if action == "wizard_upload_image" and not template.is_locked:
            uploaded = request.files.get("image_file")
            section_id = request.form.get("section_id")
            title = (request.form.get("image_title") or "").strip() or None
            if not uploaded or uploaded.filename == "":
                flash("No image selected.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            try:
                validate_upload(
                    uploaded,
                    allowed_exts=ALLOWED_IMAGE_EXTENSIONS,
                    allowed_mimetypes=ALLOWED_IMAGE_MIME_TYPES,
                    require_image=True,
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            section_obj = None
            if section_id:
                section_obj = TemplateSection.query.filter_by(id=int(section_id), template_id=template.id).first()
            if not section_obj:
                section_obj = (
                    TemplateSection.query.filter_by(template_id=template.id)
                    .order_by(TemplateSection.display_order, TemplateSection.id)
                    .first()
                )
            if not section_obj:
                flash("Add a section in Step 1 before uploading images.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

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
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            page = IllustrationPage(
                title=title,
                image_path=rel_path or "",
                status="draft",
            )
            db.session.add(page)
            db.session.flush()
            db.session.add(
                TemplateSectionIllustrationLink(
                    template_section_id=section_obj.id,
                    illustration_page_id=page.id,
                    display_order=1,
                )
            )
            db.session.commit()
            step_status["step1"] = step_status.get("step1") or {}
            step_status["step1"]["complete"] = True
            wizard.step_status = step_status
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash("Image uploaded and linked to section.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

        if action == "wizard_upload_images_folder" and not template.is_locked:
            files = request.files.getlist("image_folder")
            if not files:
                flash("No images selected.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            engine_dir = template.engine_type or "generic"
            target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "section_images", engine_dir)
            saved = 0
            for file_obj in files:
                if not file_obj or not file_obj.filename:
                    continue
                try:
                    rel_path = _save_named_section_image(file_obj, target_dir)
                    if not rel_path:
                        rel_path = save_uploaded_file(
                            file_obj,
                            subdir=f"section_images/{engine_dir}",
                            allowed_exts=ALLOWED_IMAGE_EXTENSIONS,
                            allowed_mimetypes=ALLOWED_IMAGE_MIME_TYPES,
                            require_image=True,
                        )
                except ValueError:
                    continue
                if rel_path:
                    saved += 1

            step_status["step1"] = step_status.get("step1") or {}
            step_status["step1"]["complete"] = True
            step_status["step1"]["summary"] = {"images_saved": saved}
            wizard.step_status = step_status
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash(f"Uploaded {saved} images.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

        if action == "wizard_upload_images_zip" and not template.is_locked:
            uploaded = request.files.get("image_zip")
            if not uploaded or uploaded.filename == "":
                flash("No ZIP selected.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))
            if not uploaded.filename.lower().endswith(".zip"):
                flash("Only .zip files are supported for bulk image upload.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            # Sanitize engine_type to prevent path traversal
            raw_engine = template.engine_type or "generic"
            engine_dir = secure_filename(raw_engine) or "generic"
            target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "section_images", engine_dir)
            target_dir_real = os.path.realpath(target_dir)
            upload_root_real = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
            if not target_dir_real.startswith(upload_root_real):
                flash("Invalid engine type for file storage.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))
            os.makedirs(target_dir, exist_ok=True)

            import zipfile
            try:
                zf = zipfile.ZipFile(uploaded)
            except Exception as exc:
                flash(f"Unable to read ZIP: {exc}", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

            saved = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                filename = secure_filename(os.path.basename(info.filename))
                if not filename:
                    continue
                if re.search(r"\\bcont\\b", filename.lower()):
                    continue
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    continue
                code = _extract_section_code_from_name(filename)
                try:
                    data = zf.read(info.filename)
                except Exception:
                    continue
                if code:
                    base_name = f"{secure_filename(code)}{ext}"
                    out_path = os.path.join(target_dir, base_name)
                    if os.path.exists(out_path):
                        counter = 2
                        while True:
                            candidate = f"{secure_filename(code)}-{counter}{ext}"
                            out_path = os.path.join(target_dir, candidate)
                            if not os.path.exists(out_path):
                                break
                            counter += 1
                else:
                    out_path = os.path.join(target_dir, filename)
                # Final safety: verify output stays within target_dir
                if not os.path.realpath(out_path).startswith(target_dir_real):
                    continue
                with open(out_path, "wb") as f:
                    f.write(data)
                saved += 1

            step_status["step1"] = step_status.get("step1") or {}
            step_status["step1"]["complete"] = True
            step_status["step1"]["summary"] = {"images_saved": saved}
            wizard.step_status = step_status
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash(f"Uploaded {saved} images from ZIP.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

        if action == "wizard_build_canonical" and not template.is_locked:
            summary = _build_canonical_from_items()
            step_status["step1"] = {
                "complete": True,
                "errors": [],
                "warnings": [f"{summary['skipped']} rows missing part numbers were skipped."] if summary["skipped"] else [],
                "summary": {
                    "canonical_parts": summary["parts"],
                    "occurrences": summary["occurrences"],
                    "skipped": summary["skipped"],
                },
            }
            wizard.step_status = step_status
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            if summary["skipped"]:
                flash(f"{summary['skipped']} rows missing part numbers were skipped.", "warning")
            flash("Canonical parts and occurrences generated.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="1"))

        if action == "wizard_update_rules" and not template.is_locked:
            part_id = request.form.get("part_id")
            if not part_id:
                flash("Missing part selection.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="2"))
            part = TemplatePart.query.filter_by(id=int(part_id), template_id=template.id).first()
            if not part:
                flash("Part not found.", "danger")
                return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="2"))

            always_replace = bool(request.form.get("always_replace"))
            big_ticket = bool(request.form.get("big_ticket"))
            supersedes = (request.form.get("supersedes") or "").strip()

            items = TemplateItem.query.filter_by(template_id=template.id).all()
            updated = 0
            for item in items:
                if (item.part_no or "").strip().lower() == (part.part_no or "").strip().lower():
                    item.always_replace = always_replace
                    item.big_ticket = big_ticket
                    item.supersedes = supersedes or None
                    updated += 1

            template.version = (template.version or 0) + 1
            db.session.commit()

            step_status["step2"] = {
                "complete": True,
                "errors": [],
                "warnings": [],
            }
            wizard.step_status = step_status
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash(f"Updated rules for {updated} line(s).", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="2"))

        if action == "wizard_complete_step3" and not template.is_locked:
            step_status["step3"] = {
                "complete": True,
                "errors": [],
                "warnings": [],
            }
            wizard.step_status = step_status
            wizard.current_step = max(wizard.current_step or 1, 3)
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash("Step 3 marked complete.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="3"))

        if action in ("wizard_save_measurements", "wizard_complete_step5") and not template.is_locked:
            measured_items = (
                TemplateItem.query.filter_by(template_id=template.id, requires_measurement=True)
                .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
                .all()
            )
            for item in measured_items:
                qty = item.qty if isinstance(item.qty, int) else int(item.qty or 1)
                qty = max(1, qty)
                seen_indices = set()
                for idx in range(1, qty + 1):
                    seen_indices.add(idx)
                    label = (request.form.get(f"label_{item.id}_{idx}") or "").strip() or None
                    unit = (request.form.get(f"unit_{item.id}_{idx}") or "").strip() or None
                    min_val = (request.form.get(f"min_{item.id}_{idx}") or "").strip()
                    max_val = (request.form.get(f"max_{item.id}_{idx}") or "").strip()
                    try:
                        min_dec, _ = normalize_decimal_field(min_val)
                        min_f = float(min_dec) if min_dec is not None else None
                    except ValueError:
                        min_f = None
                    try:
                        max_dec, _ = normalize_decimal_field(max_val)
                        max_f = float(max_dec) if max_dec is not None else None
                    except ValueError:
                        max_f = None
                    spec = TemplateMeasurementSpec.query.filter_by(
                        template_item_id=item.id, instance_index=idx
                    ).first()
                    if spec:
                        spec.label = label
                        spec.unit = unit
                        spec.min_value = min_f
                        spec.max_value = max_f
                    else:
                        spec = TemplateMeasurementSpec(
                            template_item_id=item.id,
                            instance_index=idx,
                            label=label,
                            unit=unit,
                            min_value=min_f,
                            max_value=max_f,
                        )
                        db.session.add(spec)
                    if idx == 1:
                        item.measurement_label = label
                        item.measurement_unit = unit
                        item.measurement_min = min_f
                        item.measurement_max = max_f
                TemplateMeasurementSpec.query.filter(
                    TemplateMeasurementSpec.template_item_id == item.id,
                    ~TemplateMeasurementSpec.instance_index.in_(seen_indices),
                ).delete(synchronize_session=False)
            if action == "wizard_complete_step5":
                step_status["step5"] = {
                    "complete": True,
                    "errors": [],
                    "warnings": [],
                }
                wizard.step_status = step_status
                wizard.current_step = max(wizard.current_step or 1, 5)
                flag_modified(wizard, "step_status")
                db.session.add(wizard)
            db.session.commit()
            if action == "wizard_complete_step5":
                flash("Step 5 marked complete.", "success")
            else:
                flash("Measurement specs saved.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="5"))

        if action in ("wizard_save_checklist", "wizard_complete_step4") and not template.is_locked:
            items = (
                TemplateItem.query.filter_by(template_id=template.id)
                .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
                .all()
            )
            for item in items:
                item.requires_torque = bool(request.form.get(f"requires_torque_{item.id}"))
                item.requires_build_measure = bool(request.form.get(f"requires_build_measure_{item.id}"))
                item.requires_photo = bool(request.form.get(f"requires_photo_{item.id}"))
            if action == "wizard_complete_step4":
                step_status["step4"] = {
                    "complete": True,
                    "errors": [],
                    "warnings": [],
                }
                wizard.step_status = step_status
                wizard.current_step = max(wizard.current_step or 1, 4)
                flag_modified(wizard, "step_status")
                db.session.add(wizard)
            db.session.commit()
            if action == "wizard_complete_step4":
                flash("Step 4 marked complete.", "success")
            else:
                flash("Checklist selections saved.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="4"))

        if action in ("wizard_save_torque", "wizard_complete_step6") and not template.is_locked:
            torque_items = (
                TemplateItem.query.filter_by(template_id=template.id, requires_torque=True)
                .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
                .all()
            )
            for item in torque_items:
                torque_val_raw = (request.form.get(f"torque_value_{item.id}") or "").strip()
                torque_unit = (request.form.get(f"torque_unit_{item.id}") or "").strip() or None
                torque_seq_raw = (request.form.get(f"torque_sequence_{item.id}") or "").strip()
                notes = (request.form.get(f"assembly_notes_{item.id}") or "").strip() or None
                try:
                    torque_dec, _ = normalize_decimal_field(torque_val_raw)
                    item.torque_value = float(torque_dec) if torque_dec is not None else None
                except ValueError:
                    item.torque_value = None
                try:
                    item.torque_sequence = int(torque_seq_raw) if torque_seq_raw else None
                except ValueError:
                    item.torque_sequence = None
                item.torque_unit = torque_unit or item.torque_unit or "Nm"
                item.assembly_notes = notes
            if action == "wizard_complete_step6":
                step_status["step6"] = {
                    "complete": True,
                    "errors": [],
                    "warnings": [],
                }
                wizard.step_status = step_status
                wizard.current_step = max(wizard.current_step or 1, 6)
                flag_modified(wizard, "step_status")
                db.session.add(wizard)
            db.session.commit()
            if action == "wizard_complete_step6":
                flash("Step 6 marked complete.", "success")
            else:
                flash("Torque data saved.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="6"))

        if action == "wizard_complete_step2" and not template.is_locked:
            step_status["step2"] = {
                "complete": True,
                "errors": [],
                "warnings": [],
            }
            wizard.step_status = step_status
            wizard.current_step = max(wizard.current_step or 1, 2)
            flag_modified(wizard, "step_status")
            db.session.add(wizard)
            db.session.commit()
            flash("Step 2 marked complete.", "success")
            return redirect(url_for("templates_bp.template_wizard", template_id=template.id, step="2"))

    ordered_sections = (
        TemplateSection.query.filter_by(template_id=template.id)
        .order_by(TemplateSection.display_order, TemplateSection.id)
        .all()
    )
    sections_text = "\n".join([s.name for s in ordered_sections])
    items = (
        TemplateItem.query.filter_by(template_id=template.id)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )
    canonical_parts = TemplatePart.query.filter_by(template_id=template.id).count()
    canonical_occurrences = TemplateOccurrence.query.filter_by(template_id=template.id).count()
    parts_list = (
        db.session.query(TemplatePart, func.count(TemplateOccurrence.id))
        .outerjoin(TemplateOccurrence, TemplateOccurrence.template_part_id == TemplatePart.id)
        .filter(TemplatePart.template_id == template.id)
        .group_by(TemplatePart.id)
        .order_by(TemplatePart.part_no)
        .all()
    )

    measured_items = (
        TemplateItem.query.filter_by(template_id=template.id, requires_measurement=True)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )
    checklist_items = items
    torque_items = (
        TemplateItem.query.filter_by(template_id=template.id, requires_torque=True)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )
    spec_map = {
        (spec.template_item_id, spec.instance_index): spec
        for spec in TemplateMeasurementSpec.query.filter(
            TemplateMeasurementSpec.template_item_id.in_([i.id for i in measured_items] or [0])
        ).all()
    }
    measurement_rows = []
    for item in measured_items:
        qty = item.qty if isinstance(item.qty, int) else int(item.qty or 1)
        qty = max(1, qty)
        for idx in range(1, qty + 1):
            spec = spec_map.get((item.id, idx))
            measurement_rows.append(
                {
                    "section": (item.section or "General").strip() or "General",
                    "item": item,
                    "index": idx,
                    "qty": qty,
                    "label": spec.label if spec and spec.label is not None else item.measurement_label,
                    "unit": spec.unit if spec and spec.unit is not None else item.measurement_unit,
                    "min": spec.min_value if spec and spec.min_value is not None else item.measurement_min,
                    "max": spec.max_value if spec and spec.max_value is not None else item.measurement_max,
                }
            )

    section_images = _build_section_images_for_template(template, current_app.config["UPLOAD_FOLDER"])
    illustrations_by_section = {}
    illustration_pages_by_section = {}
    for sec in ordered_sections:
        link = (
            TemplateSectionIllustrationLink.query
            .filter_by(template_section_id=sec.id)
            .order_by(TemplateSectionIllustrationLink.display_order, TemplateSectionIllustrationLink.id)
            .first()
        )
        if link and link.page and link.page.image_path:
            illustrations_by_section[sec.name] = url_for("uploaded_file", filename=link.page.image_path)
            illustration_pages_by_section[sec.name] = link.page

    illustration_status_by_section = {}
    page_ids = [page.id for page in illustration_pages_by_section.values()]
    labels_by_page = {}
    hotspots_by_page = {}
    if page_ids:
        for page_id, count in (
            db.session.query(IllustrationPosLabel.illustration_page_id, func.count(IllustrationPosLabel.id))
            .filter(IllustrationPosLabel.illustration_page_id.in_(page_ids))
            .group_by(IllustrationPosLabel.illustration_page_id)
            .all()
        ):
            labels_by_page[page_id] = count
        for page_id, count in (
            db.session.query(IllustrationHotspot.illustration_page_id, func.count(IllustrationHotspot.id))
            .filter(IllustrationHotspot.illustration_page_id.in_(page_ids))
            .group_by(IllustrationHotspot.illustration_page_id)
            .all()
        ):
            hotspots_by_page[page_id] = count

    for sec in ordered_sections:
        page = illustration_pages_by_section.get(sec.name)
        if not page:
            illustration_status_by_section[sec.name] = {
                "labels": 0,
                "hotspots": 0,
                "has_any": False,
            }
            continue
        labels_count = labels_by_page.get(page.id, 0)
        hotspots_count = hotspots_by_page.get(page.id, 0)
        illustration_status_by_section[sec.name] = {
            "labels": labels_count,
            "hotspots": hotspots_count,
            "has_any": bool(labels_count or hotspots_count),
        }

    pdf_wipe_item_count = TemplateItem.query.filter_by(template_id=template.id).count()
    pdf_wipe_page_count = len(page_ids)
    pdf_active_jobs_count = Job.query.filter(
        Job.template_id == template.id,
        Job.status != JobStatusEnum.COMPLETE,
    ).count()

    pdf_profiles, pdf_profiles_error = _list_pdf_profiles()

    return render_template(
        "template_wizard.html",
        template=template,
        wizard=wizard,
        step=step,
        step_status=step_status,
        sections_text=sections_text,
        sections=ordered_sections,
        canonical_parts=canonical_parts,
        canonical_occurrences=canonical_occurrences,
        parts_list=parts_list,
        items=items,
        measurement_rows=measurement_rows,
        checklist_items=checklist_items,
        torque_items=torque_items,
        template_groups=TemplateGroup.query.filter_by(template_id=template.id).order_by(TemplateGroup.label).all(),
        section_id_map={s.name: s.id for s in ordered_sections},
        section_images=section_images,
        illustrations_by_section=illustrations_by_section,
        illustration_pages_by_section=illustration_pages_by_section,
        illustration_status_by_section=illustration_status_by_section,
        pdf_profiles=pdf_profiles,
        pdf_profiles_error=pdf_profiles_error,
        pdf_wipe_item_count=pdf_wipe_item_count,
        pdf_wipe_page_count=pdf_wipe_page_count,
        pdf_active_jobs_count=pdf_active_jobs_count,
    )


@templates_bp.route("/admin/templates/<int:template_id>/costing/upload", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_costing_upload(template_id):
    template = _get_or_404(Template, template_id)

    uploaded = request.files.get("costing_file")
    if not uploaded or uploaded.filename == "":
        flash("No costing file selected.", "danger")
        return redirect(url_for("templates_bp.template_edit", template_id=template.id))

    profile_name = (request.form.get("costing_name") or "").strip() or f"{template.name} costing"
    sheet_name = (request.form.get("costing_sheet_name") or "").strip() or None
    table_start_row_raw = request.form.get("costing_table_start_row")
    try:
        table_start_row = int(table_start_row_raw) if table_start_row_raw else None
    except ValueError:
        table_start_row = None

    try:
        rel_path = save_uploaded_file(
            uploaded,
            subdir=f"costing_templates/{template.id}",
            allowed_exts=ALLOWED_COSTING_TEMPLATE_EXTENSIONS,
            allowed_mimetypes=ALLOWED_COSTING_TEMPLATE_MIME_TYPES,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("templates_bp.template_edit", template_id=template.id))

    latest_version = (
        db.session.query(func.max(CostingTemplateProfile.version))
        .filter_by(engine_template_id=template.id)
        .scalar()
        or 0
    )
    profile = CostingTemplateProfile(
        engine_template_id=template.id,
        name=profile_name,
        version=latest_version + 1,
        is_active=True,
        xlsx_template_path=rel_path,
        sheet_name=sheet_name,
        table_start_row=table_start_row,
    )
    db.session.add(profile)
    db.session.commit()

    full_path = os.path.join(current_app.config.get("UPLOAD_FOLDER") or "", rel_path or "")
    if rel_path and os.path.exists(full_path):
        try:
            if uploaded.filename.lower().endswith(".csv"):
                df = pd.read_csv(full_path)
            else:
                df = pd.read_excel(full_path, sheet_name=sheet_name)
        except Exception as exc:
            flash(f"Costing file saved, but could not parse rows: {exc}", "warning")
        else:
            df.columns = [c.strip().lower() for c in df.columns]

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

            col_part = col("system_part_number", "part_no", "part no", "part number", "partnumber", "part")
            col_oem = col("oem_part_no", "oem part no", "oem part number", "oem")
            col_desc = col("description", "part_description", "part name", "item description")
            col_supplier = col("supplier", "intended supplier", "latest supplier")
            col_cost = col("latest_cost", "cost", "unit cost", "price")
            col_menu = col("menu_sell_price_unit", "menu price", "sell price")

            created = 0
            for idx in range(len(df)):
                part_no = str(col_part.iloc[idx]) if col_part is not None and not pd.isna(col_part.iloc[idx]) else ""
                oem_no = str(col_oem.iloc[idx]) if col_oem is not None and not pd.isna(col_oem.iloc[idx]) else ""
                if not part_no and not oem_no:
                    continue
                desc = str(col_desc.iloc[idx]) if col_desc is not None and not pd.isna(col_desc.iloc[idx]) else None
                supplier = (
                    str(col_supplier.iloc[idx])
                    if col_supplier is not None and not pd.isna(col_supplier.iloc[idx])
                    else None
                )

                def _parse_decimal(val):
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        return None

                cost = (
                    _parse_decimal(col_cost.iloc[idx])
                    if col_cost is not None and not pd.isna(col_cost.iloc[idx])
                    else None
                )
                menu_price = (
                    _parse_decimal(col_menu.iloc[idx])
                    if col_menu is not None and not pd.isna(col_menu.iloc[idx])
                    else None
                )

                line = CostingTemplateLine(
                    costing_template_profile_id=profile.id,
                    line_no=idx + 1,
                    system_part_number=part_no or None,
                    oem_part_no=oem_no or None,
                    part_description=desc,
                    default_intended_supplier=supplier,
                    default_latest_supplier=supplier,
                    default_latest_cost=cost,
                    default_menu_sell_price=menu_price,
                )
                db.session.add(line)
                created += 1
            db.session.commit()
            if created:
                flash(f"Loaded {created} costing line(s) into the catalogue.", "success")

    flash(f"Costing template uploaded as version {profile.version}.", "success")
    return redirect(url_for("templates_bp.template_edit", template_id=template.id))


@templates_bp.route("/admin/templates/<int:template_id>/measurements", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_measurements(template_id):
    template = _get_or_404(Template, template_id)
    measured_items = (
        TemplateItem.query.filter_by(template_id=template.id, requires_measurement=True)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )

    if request.method == "POST":
        for item in measured_items:
            item.measurement_label = (request.form.get(f"label_{item.id}") or "").strip() or None
            item.measurement_unit = (request.form.get(f"unit_{item.id}") or "").strip() or None
            min_val = (request.form.get(f"min_{item.id}") or "").strip()
            max_val = (request.form.get(f"max_{item.id}") or "").strip()
            try:
                min_dec, _ = normalize_decimal_field(min_val)
                item.measurement_min = float(min_dec) if min_dec is not None else None
            except ValueError:
                item.measurement_min = None
            try:
                max_dec, _ = normalize_decimal_field(max_val)
                item.measurement_max = float(max_dec) if max_dec is not None else None
            except ValueError:
                item.measurement_max = None
        db.session.commit()
        flash("Measurement specs updated.", "success")
        return redirect(url_for("templates_bp.template_measurements", template_id=template.id))

    return render_template(
        "template_measurements.html",
        template=template,
        measured_items=measured_items,
    )


@templates_bp.route("/admin/templates/<int:template_id>/delete", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def template_delete(template_id):
    template = _get_or_404(Template, template_id)
    db.session.delete(template)
    db.session.commit()
    flash("Template deleted.", "success")
    return redirect(url_for("templates_bp.templates_list"))
