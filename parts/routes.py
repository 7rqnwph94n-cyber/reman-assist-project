import io
import csv

from flask import Blueprint, flash, redirect, render_template, request, url_for, Response, abort, current_app

from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from models import (
    db,
    Job,
    PartRequirement,
    SurveyItem,
    TemplateItem,
    StoreItem,
    StockStatusEnum,
    RoleEnum,
    JobStatusEnum,
    PickList,
    PickListItem,
    PickListStatusEnum,
    User,
    CostingSheet,
    CostingLine,
    InvalidJobTransition,
)
from auth_utils import login_required
from auth_utils import current_user, require_job_access, roles_required, job_access_required, get_org_filter, get_scoped_or_404
from services.job_services import log_event, change_job_status, is_job_locked
from services.job_pack_revision import bump_revision
from utils.pagination import parse_int, parse_int_arg
from utils.localization import t
from datetime import datetime, timezone, date

parts_bp = Blueprint("parts", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)


def build_store_overlay(job, parts):
    """
    Overlay Stores data onto BOM lines for this job.
    Returns: dict[part_id] -> {"store": StoreItem, "stock": int, "required": int, "enough": bool}
    """
    overlay = {}

    if not job.template_id:
        return overlay

    # Eager load store_item relationship to prevent N+1 queries
    template_items = (
        TemplateItem.query
        .filter_by(template_id=job.template_id)
        .options(joinedload(TemplateItem.store_item))
        .all()
    )

    template_store_lookup = {}
    for ti in template_items:
        store = ti.store_item
        if not store:
            continue

        key = (
            (ti.part_no or "").strip(),
            (ti.section or "").strip(),
            ti.pos or 0,
        )
        template_store_lookup[key] = store

    for p in parts:
        key = (
            (p.part_no or "").strip(),
            (p.section or "").strip(),
            p.pos or 0,
        )
        store = template_store_lookup.get(key)
        if not store:
            continue

        stock = store.qty_in_stock or 0
        required = p.qty_required or 0

        overlay[p.id] = {
            "store": store,
            "stock": stock,
            "required": required,
            "enough": stock >= required if required > 0 else stock > 0,
        }

    return overlay


@parts_bp.route("/jobs/<int:job_id>/parts", methods=["GET", "POST"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_parts(job_id):
    job = _get_or_404(Job, job_id)
    filter_status = (request.args.get("status") or "").strip().lower()
    unapproved_only = (request.args.get("unapproved") or "0") == "1"

    def _filter_query(base, search, status_raw, unapproved_only_flag):
        if search:
            like_term = f"%{search}%"
            base = base.filter(
                or_(
                    PartRequirement.part_no.ilike(like_term),
                    PartRequirement.name.ilike(like_term),
                    PartRequirement.section.ilike(like_term),
                )
            )
        if status_raw:
            try:
                status_enum = StockStatusEnum(status_raw)
            except ValueError:
                status_enum = None
            if status_enum:
                base = base.filter(PartRequirement.stock_status == status_enum)
        if unapproved_only_flag:
            base = base.filter(PartRequirement.approved.is_(False))
        return base
    if request.method == "POST":
        if is_job_locked(job, current_user()):
            flash("Job is complete and read-only. Admin can reopen if needed.", "warning")
            return redirect(url_for("parts.job_parts", job_id=job.id))
        action = request.form.get("action", "save")
        next_url = (request.form.get("next") or "").strip()
        search_query = (request.form.get("q") or "").strip().lower()
        filter_status = (request.form.get("status") or "").strip().lower()
        unapproved_only = (request.form.get("unapproved") or "0") == "1"
        page = _parse_int(request.form.get("page"), 1)
        per_page = _parse_int(
            request.form.get("per_page"),
            current_app.config.get("PARTS_PAGE_SIZE", 50),
        )
        try:
            expected_version = int(request.form.get("parts_version") or 0)
        except ValueError:
            expected_version = 0
        if expected_version != job.parts_version:
            flash("Parts list has changed on another terminal. Please reload and try again.", "danger")
            return redirect(url_for("parts.job_parts", job_id=job.id))

        parts_all = (
            PartRequirement.query
            .filter_by(job_id=job.id)
            .order_by(
                PartRequirement.section,
                PartRequirement.pos,
                PartRequirement.id,
            )
            .all()
        )
        prefixes = ("qty_", "stock_status_", "supplier_", "po_number_", "notes_", "approved_")
        part_ids = {
            int(key.split("_", 1)[1])
            for key in request.form.keys()
            if key.startswith(prefixes) and key.split("_", 1)[1].isdigit()
        }
        parts_for_update = [p for p in parts_all if p.id in part_ids]

        missing_backorder_notes = []
        for part in parts_for_update:
            qty_raw = (request.form.get(f"qty_{part.id}") or "").strip()
            stock_status_raw = request.form.get(f"stock_status_{part.id}")
            supplier = (request.form.get(f"supplier_{part.id}") or "").strip()
            po_number = (request.form.get(f"po_number_{part.id}") or "").strip()
            notes_key = f"notes_{part.id}"
            notes = None
            if notes_key in request.form:
                notes = (request.form.get(notes_key) or "").strip()
            approved_flag = request.form.get(f"approved_{part.id}") == "on"

            if qty_raw:
                try:
                    part.qty_required = int(qty_raw)
                except ValueError:
                    pass

            if stock_status_raw in [s.value for s in StockStatusEnum]:
                part.stock_status = StockStatusEnum(stock_status_raw)

            part.supplier = supplier or None
            part.po_number = po_number or None
            if notes is not None:
                part.notes = notes or None
            if part.po_number and part.stock_status == StockStatusEnum.TO_ORDER:
                part.stock_status = StockStatusEnum.ORDERED
            if part.stock_status == StockStatusEnum.BACKORDER and not notes:
                missing_backorder_notes.append(part.part_no or part.name or str(part.id))
            if approved_flag:
                part.approved = True
                part.approved_by_id = current_user().id if current_user() else None
                part.approved_at = datetime.now(timezone.utc)
            else:
                part.approved = False
                part.approved_by_id = None
                part.approved_at = None

        if missing_backorder_notes:
            db.session.rollback()
            flash("Backorder requires a note/reason on the part line.", "danger")
            return redirect(url_for("parts.job_parts", job_id=job.id))

        store_info = build_store_overlay(job, parts_all)

        for part in parts_all:
            info = store_info.get(part.id)
            if not info:
                continue

            required = part.qty_required or 0
            stock = info.get("stock", 0)

            if part.stock_status in (
                StockStatusEnum.NOT_REQUIRED,
                StockStatusEnum.FITTED,
                StockStatusEnum.ORDERED,
                StockStatusEnum.RECEIVED,
                StockStatusEnum.BACKORDER,
            ):
                continue

            if required > 0 and stock >= required:
                part.stock_status = StockStatusEnum.IN_STOCK
            else:
                part.stock_status = StockStatusEnum.TO_ORDER

        if action == "move_to_build":
            try:
                change_job_status(job, JobStatusEnum.BUILD, user=current_user(), reason="Parts moved to build")
            except InvalidJobTransition as exc:
                flash(str(exc), "danger")
                return redirect(url_for("parts.job_parts", job_id=job.id))

        if action == "issue_picklist":
            enforce_gate = current_app.config.get("ENFORCE_PICKLIST_READY", False)
            if enforce_gate:
                unapproved = [p for p in parts_all if not p.approved]
                not_ordered = [
                    p
                    for p in parts_all
                    if p.stock_status in (StockStatusEnum.PENDING, StockStatusEnum.TO_ORDER, StockStatusEnum.BACKORDER)
                ]
                if unapproved or not_ordered:
                    msg_parts = []
                    if unapproved:
                        msg_parts.append(f"{len(unapproved)} line(s) not approved")
                    if not_ordered:
                        msg_parts.append(f"{len(not_ordered)} line(s) not ordered/in stock")
                    flash(
                        "Cannot issue pick list – " + "; ".join(msg_parts) + ".",
                        "danger",
                    )
                    return redirect(url_for("parts.job_parts", job_id=job.id))

            # Create a pick list and copy current BOM lines
            picklist = PickList(
                job_id=job.id,
                organization_id=job.organization_id,
                status=PickListStatusEnum.NEW,
            )
            db.session.add(picklist)
            db.session.flush()

            for part in parts_all:
                pli = PickListItem(
                    pick_list_id=picklist.id,
                    organization_id=job.organization_id,
                    part_no=part.part_no or "",
                    name=part.name,
                    bin_location="",
                    qty_required=part.qty_required or 0,
                    stock_at_issue=0,
                )
                db.session.add(pli)

            flash(f"Pick list #{picklist.id} issued for job {job.job_number}.", "success")

        if action in {"approve_ready_page", "approve_ready_all"}:
            base_query = PartRequirement.query.filter_by(job_id=job.id)
            base_query = _filter_query(base_query, search_query, filter_status, unapproved_only)
            if action == "approve_ready_page":
                per_page = max(1, min(per_page, current_app.config.get("PARTS_PAGE_MAX", 200)))
                page = max(1, page)
                parts_ready = (
                    base_query
                    .order_by(PartRequirement.section, PartRequirement.pos, PartRequirement.id)
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                    .all()
                )
            else:
                parts_ready = base_query.all()

            ready_statuses = {
                StockStatusEnum.IN_STOCK,
                StockStatusEnum.RECEIVED,
                StockStatusEnum.FITTED,
                StockStatusEnum.NOT_REQUIRED,
            }
            approved_count = 0
            for part in parts_ready:
                if part.stock_status in ready_statuses and not part.approved:
                    part.approved = True
                    part.approved_by_id = current_user().id if current_user() else None
                    part.approved_at = datetime.now(timezone.utc)
                    approved_count += 1
            log_event(
                action="parts_bulk_approved",
                message=f"Bulk approved {approved_count} line(s) ({action})",
                job=job,
                user=current_user(),
            )

        job.parts_version = (job.parts_version or 0) + 1
        log_event(
            action="parts_updated",
            message=f"Parts list updated (action={action})",
            job=job,
            user=current_user(),
        )
        bump_revision(job, f"parts_updated:{action}", user=current_user())
        db.session.commit()

        if action == "move_to_build":
            flash("Parts list saved. Job moved to Build.", "success")
            return redirect(url_for("jobs.job_build", job_id=job.id))

        if action == "issue_picklist":
            return redirect(url_for("stores.stores_hub", view="picklists"))

        if next_url.startswith("/") and not next_url.startswith("//"):
            flash("Parts list updated.", "success")
            return redirect(next_url)

        flash("Parts list updated.", "success")
        return redirect(url_for("parts.job_parts", job_id=job.id))

    search_query = (request.args.get("q") or "").strip().lower()

    per_page = parse_int_arg("per_page", current_app.config.get("PARTS_PAGE_SIZE", 50))
    per_page = max(1, min(per_page, current_app.config.get("PARTS_PAGE_MAX", 200)))
    page = parse_int_arg("page", 1)
    if page < 1:
        page = 1

    base_query = PartRequirement.query.filter_by(job_id=job.id)
    parts_query = _filter_query(base_query, search_query, filter_status, unapproved_only)

    total_parts = base_query.count()
    filtered_count = parts_query.count()
    total_pages = max(1, (filtered_count + per_page - 1) // per_page) if filtered_count else 1
    if page > total_pages:
        page = total_pages

    parts = (
        parts_query
        .order_by(
            PartRequirement.section,
            PartRequirement.pos,
            PartRequirement.id,
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    store_info = build_store_overlay(job, parts)

    unapproved_count = (
        base_query
        .filter(PartRequirement.approved.is_(False))
        .count()
    )
    not_ordered_count = (
        base_query
        .filter(PartRequirement.stock_status.in_([
            StockStatusEnum.PENDING,
            StockStatusEnum.TO_ORDER,
            StockStatusEnum.BACKORDER,
        ]))
        .count()
    )

    # Derive status for display: if store has enough, treat as IN_STOCK
    for p in parts:
        info = store_info.get(p.id) if store_info else None
        derived = p.stock_status
        stock_val = None
        bin_val = None
        if info:
            required = p.qty_required or 0
            stock = info.get("stock", 0)
            stock_val = stock
            bin_val = info.get("store").bin_location if info.get("store") else None
            if required > 0 and stock >= required:
                derived = StockStatusEnum.IN_STOCK
        elif getattr(p, "store_item", None):
            required = p.qty_required or 0
            stock = p.store_item.qty_in_stock or 0
            stock_val = stock
            bin_val = p.store_item.bin_location
            if required > 0 and stock >= required:
                derived = StockStatusEnum.IN_STOCK
        p.derived_status = derived
        p.derived_stock = stock_val
        p.derived_bin = bin_val

    status_counts = {s.value: 0 for s in StockStatusEnum}
    status_rows = (
        db.session.query(PartRequirement.stock_status, func.count())
        .filter(PartRequirement.job_id == job.id)
        .group_by(PartRequirement.stock_status)
        .all()
    )
    for status, count in status_rows:
        if status:
            status_counts[status.value] = count

    always_parts = []
    test_parts = []
    big_ticket_parts = []
    kit_parts_by_name = {}
    standard_parts = []

    for p in parts:
        si = getattr(p, "survey_item", None)

        if not si:
            standard_parts.append(p)
            continue

        if getattr(si, "always_replace", False):
            always_parts.append(p)
        elif getattr(si, "requires_test", False):
            test_parts.append(p)
        elif getattr(si, "big_ticket", False):
            big_ticket_parts.append(p)
        elif getattr(si, "kit_name", None):
            kit_name = si.kit_name
            kit_parts_by_name.setdefault(kit_name, []).append(p)
        else:
            standard_parts.append(p)

    procurement_count = (
        base_query
        .filter(PartRequirement.stock_status.in_([
            StockStatusEnum.TO_ORDER,
            StockStatusEnum.ORDERED,
            StockStatusEnum.BACKORDER,
        ]))
        .count()
    )
    cost_by_part_id = {}
    sheet = CostingSheet.query.filter_by(job_id=job.id).first()
    if sheet:
        lines = CostingLine.query.filter_by(costing_sheet_id=sheet.id).all()
        for line in lines:
            if not line.part_requirement_id:
                continue
            cost_val = line.unit_cost_confirmed or line.latest_cost or line.price_cost
            cost_by_part_id[line.part_requirement_id] = cost_val
    total_cost_full = 0
    for part in base_query.all():
        cost_val = cost_by_part_id.get(part.id)
        if cost_val is None:
            continue
        try:
            qty = part.qty_required or 0
            total_cost_full += float(cost_val) * qty
        except (TypeError, ValueError):
            continue

    read_only = is_job_locked(job, current_user())
    return render_template(
        "parts.html",
        job=job,
        read_only=read_only,
        search_query=search_query,
        filter_status=filter_status,
        unapproved_only=unapproved_only,
        procurement_count=procurement_count,
        total_parts=total_parts,
        filtered_count=filtered_count,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        standard_parts=standard_parts,
        always_parts=always_parts,
        test_parts=test_parts,
        big_ticket_parts=big_ticket_parts,
        kit_parts_by_name=kit_parts_by_name,
        store_info=store_info,
        unapproved_count=unapproved_count,
        not_ordered_count=not_ordered_count,
        status_counts=status_counts,
        StockStatusEnum=StockStatusEnum,
        return_url=request.full_path,
        cost_by_part_id=cost_by_part_id,
        total_cost_full=total_cost_full,
    )


@parts_bp.route("/jobs/<int:job_id>/parts/procurement", methods=["GET", "POST"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_parts_procurement(job_id):
    job = _get_or_404(Job, job_id)
    next_url = request.form.get("next") if request.method == "POST" else request.args.get("next")

    def _form_or_arg(name):
        return request.form.get(name) if request.method == "POST" else request.args.get(name)

    per_page = parse_int(_form_or_arg("per_page"), current_app.config.get("PARTS_PAGE_SIZE", 50))
    per_page = max(1, min(per_page, current_app.config.get("PARTS_PAGE_MAX", 200)))
    page = parse_int(_form_or_arg("page"), 1)
    if page < 1:
        page = 1

    base_query = (
        PartRequirement.query
        .filter(
            PartRequirement.job_id == job.id,
            PartRequirement.stock_status.in_([
                StockStatusEnum.TO_ORDER,
                StockStatusEnum.ORDERED,
                StockStatusEnum.BACKORDER,
            ]),
        )
    )
    total_parts = base_query.count()
    total_pages = max(1, (total_parts + per_page - 1) // per_page) if total_parts else 1
    if page > total_pages:
        page = total_pages

    procurement_parts = (
        base_query
        .order_by(PartRequirement.section, PartRequirement.pos, PartRequirement.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    cost_by_part_id = {}
    sheet = CostingSheet.query.filter_by(job_id=job.id).first()
    if sheet:
        lines = CostingLine.query.filter_by(costing_sheet_id=sheet.id).all()
        for line in lines:
            if not line.part_requirement_id:
                continue
            cost_val = line.unit_cost_confirmed or line.latest_cost or line.price_cost
            cost_by_part_id[line.part_requirement_id] = cost_val
    procurement_total_cost = 0
    for part in base_query.all():
        cost_val = cost_by_part_id.get(part.id)
        if cost_val is None:
            continue
        try:
            qty = part.qty_required or 0
            procurement_total_cost += float(cost_val) * qty
        except (TypeError, ValueError):
            continue

    if request.method == "POST":
        action = request.form.get("action") or "save"
        try:
            expected_version = int(request.form.get("parts_version") or 0)
        except ValueError:
            expected_version = 0
        if expected_version != job.parts_version:
            flash("Parts list has changed on another terminal. Please reload and try again.", "danger")
            return redirect(url_for("parts.job_parts_procurement", job_id=job.id))
        selected_ids = {
            int(pid)
            for pid in request.form.getlist("selected_ids")
            if pid and pid.isdigit()
        }
        bulk_supplier = (request.form.get("bulk_supplier") or "").strip()
        bulk_po = (request.form.get("bulk_po") or "").strip()
        bulk_backorder_reason = (request.form.get("bulk_backorder_reason") or "").strip()
        if action == "bulk_mark_backorder" and not bulk_backorder_reason:
            flash("Backorder requires a reason.", "danger")
            return redirect(url_for("parts.job_parts_procurement", job_id=job.id))

        parts_for_action = procurement_parts
        if action != "save" and selected_ids:
            parts_for_action = (
                PartRequirement.query
                .filter(
                    PartRequirement.job_id == job.id,
                    PartRequirement.id.in_(selected_ids),
                )
                .all()
            )

        for part in parts_for_action:
            if action != "save" and selected_ids and part.id not in selected_ids:
                continue

            status_raw = request.form.get(f"stock_status_{part.id}") or ""
            supplier = (request.form.get(f"supplier_{part.id}") or "").strip()
            po_number = (request.form.get(f"po_number_{part.id}") or "").strip()
            notes = (request.form.get(f"notes_{part.id}") or "").strip()
            backorder_reason = (request.form.get(f"backorder_reason_{part.id}") or "").strip()
            received_raw = (request.form.get(f"received_{part.id}") or "").strip()

            if action == "bulk_set_supplier_po":
                if bulk_supplier:
                    part.supplier = bulk_supplier
                if bulk_po:
                    part.po_number = bulk_po
                if part.po_number and part.stock_status == StockStatusEnum.TO_ORDER:
                    part.stock_status = StockStatusEnum.ORDERED
            else:
                part.supplier = supplier or None
                part.po_number = po_number or None
            if notes is not None:
                part.notes = notes or None

            if action == "bulk_mark_ordered":
                part.stock_status = StockStatusEnum.ORDERED
            elif action == "bulk_mark_backorder":
                part.stock_status = StockStatusEnum.BACKORDER
            elif status_raw in [s.value for s in StockStatusEnum]:
                part.stock_status = StockStatusEnum(status_raw)

            if part.stock_status == StockStatusEnum.BACKORDER:
                if action == "bulk_mark_backorder":
                    part.backorder_reason = bulk_backorder_reason
                else:
                    if not backorder_reason:
                        flash("Backorder requires a reason.", "danger")
                        db.session.rollback()
                        return redirect(url_for("parts.job_parts_procurement", job_id=job.id))
                    part.backorder_reason = backorder_reason
            elif backorder_reason:
                part.backorder_reason = backorder_reason

            if action == "bulk_mark_received_full":
                part.qty_received = part.qty_required or 0
                part.received_at = datetime.now(timezone.utc)
                part.received_by_id = current_user().id if current_user() else None
                part.stock_status = StockStatusEnum.RECEIVED
                log_event(
                    action="part_received",
                    message=f"Received {part.qty_received}/{part.qty_required or 0} for {part.part_no or part.name}",
                    job=job,
                    user=current_user(),
                )
            elif received_raw:
                try:
                    received_val = int(received_raw)
                except ValueError:
                    received_val = None
                if received_val is not None:
                    part.qty_received = max(received_val, 0)
                    part.received_at = datetime.now(timezone.utc)
                    part.received_by_id = current_user().id if current_user() else None
                    if part.qty_required and part.qty_received >= part.qty_required:
                        part.stock_status = StockStatusEnum.RECEIVED
                    elif part.qty_received > 0:
                        part.stock_status = StockStatusEnum.ORDERED
                    log_event(
                        action="part_received",
                        message=f"Received {part.qty_received}/{part.qty_required or 0} for {part.part_no or part.name}",
                        job=job,
                        user=current_user(),
                    )

        job.parts_version = (job.parts_version or 0) + 1
        log_event(
            action="procurement_updated",
            message=f"Procurement updates saved (action={action})",
            job=job,
            user=current_user(),
        )
        db.session.commit()
        flash("Procurement updates saved.", "success")
        return redirect(
            url_for(
                "parts.job_parts_procurement",
                job_id=job.id,
                page=page,
                per_page=per_page,
                next=next_url or None,
            )
        )

    return render_template(
        "parts_procurement.html",
        job=job,
        parts=procurement_parts,
        cost_by_part_id=cost_by_part_id,
        StockStatusEnum=StockStatusEnum,
        page=page,
        per_page=per_page,
        total_parts=total_parts,
        total_pages=total_pages,
        next_url=next_url,
        procurement_total_cost=procurement_total_cost,
    )


@parts_bp.route("/jobs/<int:job_id>/parts/export", methods=["GET"])
@login_required
@job_access_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_parts_export(job_id):
    job = _get_or_404(Job, job_id)

    parts = (
        PartRequirement.query
        .filter_by(job_id=job.id)
        .order_by(
            PartRequirement.section,
            PartRequirement.pos,
            PartRequirement.id,
        )
        .all()
    )
    survey_items = {
        si.id: si
        for si in SurveyItem.query.filter_by(job_id=job.id).all()
    }

    output = io.StringIO()
    writer = csv.writer(output)

    def category_for(part):
        si = survey_items.get(getattr(part, "survey_item_id", None))
        if si and getattr(si, "always_replace", False):
            return "100% items"
        if si and getattr(si, "big_ticket", False):
            return "Big-ticket items"
        return "Standard items"

    buckets = {"100% items": [], "Standard items": [], "Big-ticket items": []}
    for p in parts:
        buckets[category_for(p)].append(p)

    # Header with job info
    writer.writerow(["Job number", job.job_number])
    writer.writerow(["Customer", job.customer_name or ""])
    writer.writerow(["Engine type", job.engine_type or ""])
    writer.writerow(["Status", job.status.value if job.status else ""])
    writer.writerow([])

    headers = [
        "Part no",
        "Name",
        "Qty required",
        "Decision type",
        "Measurement findings",
        "Supplier",
        "Notes",
    ]

    for label in ["100% items", "Standard items", "Big-ticket items"]:
        writer.writerow([label])
        writer.writerow(headers)
        for p in buckets[label]:
            si = survey_items.get(getattr(p, "survey_item_id", None))
            decision_type = "Replace"
            if si and getattr(si, "always_replace", False):
                decision_type = "Always Replace"
            measurement_findings = ""
            if si:
                status = si.measurement_result.value if getattr(si, "measurement_result", None) else ""
                value = si.measurement_value or ""
                unit = si.measurement_unit or ""
                min_val = si.spec_min or ""
                max_val = si.spec_max or ""
                if value or min_val or max_val or status:
                    measurement_findings = f"{value}{unit} (min {min_val} max {max_val}) [{status}]".strip()
            writer.writerow([
                p.part_no or "",
                p.name or "",
                p.qty_required or "",
                decision_type,
                measurement_findings,
                p.supplier or "",
                (p.notes or "").replace("\n", " "),
            ])
        writer.writerow([])

    csv_data = output.getvalue()
    today = date.today().isoformat()
    draft_suffix = ""
    if job.status in {JobStatusEnum.PRE_SURVEY, JobStatusEnum.SURVEY}:
        draft_suffix = "_(DRAFT)"
    filename = f"Demand_List_Job{job.job_number}_{today}{draft_suffix}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )
