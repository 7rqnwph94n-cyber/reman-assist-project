from flask import Blueprint, flash, redirect, render_template, request, url_for, abort, current_app
import csv
from io import StringIO
from math import ceil

from sqlalchemy import case, func

from models import (
    db,
    Template,
    TemplateItem,
    StoreItem,
    RoleEnum,
    PickList,
    PickListItem,
    PickListStatusEnum,
    Job,
    PartRequirement,
    StockStatusEnum,
    JobStatusEnum,
    InvalidJobTransition,
)
from auth_utils import login_required, roles_required, current_user, get_org_filter, get_scoped_or_404
from utils.pagination import parse_int, parse_int_arg
from services.job_services import log_event, change_job_status, is_job_locked
from services.job_pack_revision import bump_revision
from utils.localization import t
from datetime import datetime, timezone

stores_bp = Blueprint("stores", __name__)


def _get_or_404(model, ident):
    return get_scoped_or_404(model, ident)


def _get_picklist_or_404(picklist_id: int) -> PickList:
    """
    Resolve picklist with strict org scoping.
    """
    org_id = get_org_filter()
    picklist = PickList.query.filter_by(id=picklist_id, organization_id=org_id).first()
    if not picklist:
        abort(404)
    return picklist


def _decorate_store_items(store_items):
    for si in store_items:
        et = None
        tpl_item = getattr(si, "template_item", None)
        if tpl_item is not None and getattr(tpl_item, "template", None):
            et = tpl_item.template.engine_type
        si.engine_types = [et] if et else []
    return store_items


def _store_item_query_for_org(org_id):
    return StoreItem.query.filter(StoreItem.organization_id == org_id)


def _store_item_for_org(org_id: int, store_id: int) -> StoreItem | None:
    return _store_item_query_for_org(org_id).filter(StoreItem.id == store_id).first()


@stores_bp.route("/admin/templates/<int:template_id>/stores/seed", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def stores_seed(template_id):
    template = _get_or_404(Template, template_id)

    template_items = (
        TemplateItem.query
        .filter_by(template_id=template.id)
        .order_by(TemplateItem.section, TemplateItem.pos)
        .all()
    )

    created = 0

    for ti in template_items:
        if ti.store_item:
            continue

        dummy_stock = 10 if getattr(ti, "always_replace", False) else 4
        dummy_min = 2

        store = StoreItem(
            template_item=ti,
            organization_id=template.organization_id,
            engine_type=template.engine_type,
            bin_location="",
            qty_in_stock=dummy_stock,
            min_stock=dummy_min,
            notes="",
        )

        db.session.add(store)
        created += 1

    db.session.commit()
    flash(f"Seeded {created} {t('parts_room_lower')} lines from template «{template.name}».", "success")
    return redirect(url_for("stores.stores_hub", view="engine"))


@stores_bp.route("/stores", methods=["GET"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.STORES.value)
def stores_hub():
    view = request.args.get("view") or "engine"
    org_id = get_org_filter()
    if view == "per_engine":
        view = "engine"

    if view == "barcodes":
        if current_user().role not in (RoleEnum.ADMIN, RoleEnum.STORES):
            abort(403)
        per_page = parse_int_arg("per_page", current_app.config.get("STORES_BARCODE_PAGE_SIZE", 100))
        per_page = max(1, min(per_page, current_app.config.get("STORES_BARCODE_PAGE_MAX", 200)))
        page = parse_int_arg("page", 1)
        if page < 1:
            page = 1
        q = _store_item_query_for_org(org_id).order_by(StoreItem.id)
        total = q.count()
        total_pages = max(1, ceil(total / per_page)) if total else 1
        if page > total_pages:
            page = total_pages
        store_items = q.offset((page - 1) * per_page).limit(per_page).all()
        _decorate_store_items(store_items)
        return render_template(
            "stores.html",
            view_mode="barcodes",
            store_items=store_items,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            total=total,
        )

    if view == "picklists":
        per_page = parse_int_arg("per_page", current_app.config.get("STORES_PICKLIST_PAGE_SIZE", 50))
        per_page = max(1, min(per_page, current_app.config.get("STORES_PICKLIST_PAGE_MAX", 200)))
        page = parse_int_arg("page", 1)
        if page < 1:
            page = 1
        q = (
            PickList.query
            .filter(PickList.organization_id == org_id)
            .order_by(PickList.created_at.desc())
        )
        total = q.count()
        total_pages = max(1, ceil(total / per_page)) if total else 1
        if page > total_pages:
            page = total_pages
        picklists = q.offset((page - 1) * per_page).limit(per_page).all()
        # Eagerly load related job to avoid N+1 in template
        jobs = {pl.job_id: pl.job for pl in picklists if pl.job_id}
        return render_template(
            "stores.html",
            view_mode="picklists",
            picklists=picklists,
            jobs=jobs,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            total=total,
        )

    if view == "engine":
        selected_engine_type = request.args.get("engine_type") or None
        per_page = parse_int_arg("per_page", current_app.config.get("STORES_ENGINE_PAGE_SIZE", 24))
        per_page = max(1, min(per_page, current_app.config.get("STORES_ENGINE_PAGE_MAX", 200)))
        page = parse_int_arg("page", 1)
        if page < 1:
            page = 1

        templates_query = (
            db.session.query(
                Template.id,
                Template.name,
                Template.engine_type,
                func.count(TemplateItem.id).label("total_parts"),
                func.coalesce(func.sum(StoreItem.qty_in_stock), 0).label("total_stock"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (StoreItem.min_stock > 0)
                                & (StoreItem.qty_in_stock < StoreItem.min_stock),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("below_min"),
            )
            .outerjoin(TemplateItem, TemplateItem.template_id == Template.id)
            .outerjoin(StoreItem, StoreItem.template_item_id == TemplateItem.id)
            .filter(Template.organization_id == org_id)
            .group_by(Template.id)
            .order_by(Template.engine_type, Template.name)
        )
        count_query = Template.query.filter(Template.organization_id == org_id)
        if selected_engine_type:
            templates_query = templates_query.filter(Template.engine_type == selected_engine_type)
            count_query = count_query.filter(Template.engine_type == selected_engine_type)

        total = count_query.count()
        total_pages = max(1, ceil(total / per_page)) if total else 1
        if page > total_pages:
            page = total_pages

        template_rows = (
            templates_query
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        engine_summaries = [
            {
                "template_id": row.id,
                "template_name": row.name,
                "engine_type": row.engine_type,
                "total_parts": row.total_parts or 0,
                "total_stock": row.total_stock or 0,
                "below_min": row.below_min or 0,
            }
            for row in template_rows
        ]

        engine_types = sorted({
            et
            for (et,) in db.session.query(Template.engine_type)
            .filter(Template.organization_id == org_id)
            .distinct()
            .all()
            if et
        })

        return render_template(
            "stores.html",
            view_mode=view,
            engine_summaries=engine_summaries,
            engine_types=engine_types,
            selected_engine_type=selected_engine_type,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            total=total,
        )

    q = _store_item_query_for_org(org_id)
    if view == "consumables" and hasattr(StoreItem, "is_consumable"):
        q = q.filter_by(is_consumable=True)

    per_page = parse_int_arg("per_page", current_app.config.get("STORES_PAGE_SIZE", 100))
    per_page = max(1, min(per_page, current_app.config.get("STORES_PAGE_MAX", 200)))
    page = parse_int_arg("page", 1)
    if page < 1:
        page = 1
    total = q.count()
    total_pages = max(1, ceil(total / per_page)) if total else 1
    if page > total_pages:
        page = total_pages
    store_items = q.order_by(StoreItem.id).offset((page - 1) * per_page).limit(per_page).all()
    _decorate_store_items(store_items)

    return render_template(
        "stores.html",
        view_mode=view,
        store_items=store_items,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total=total,
    )


@stores_bp.route("/stores/template/<int:template_id>", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value, RoleEnum.STORES.value)
def stores_for_template(template_id):
    template = _get_or_404(Template, template_id)

    items = (
        TemplateItem.query
        .filter_by(template_id=template.id)
        .order_by(TemplateItem.section, TemplateItem.pos, TemplateItem.id)
        .all()
    )

    if request.method == "POST":
        for key, value in request.form.items():
            if "_" not in key:
                continue

            prefix, raw_id = key.split("_", 1)
            if prefix not in {"bin", "stock", "min_stock", "notes"}:
                continue

            try:
                ti_id = int(raw_id)
            except ValueError:
                continue

            ti = TemplateItem.query.filter_by(id=ti_id, template_id=template.id).first()
            if not ti or not ti.store_item:
                continue

            store = ti.store_item

            if prefix == "bin":
                store.bin_location = (value or "").strip()
            elif prefix == "stock":
                try:
                    store.qty_in_stock = int(value or 0)
                except ValueError:
                    store.qty_in_stock = 0
            elif prefix == "min_stock":
                try:
                    store.min_stock = int(value or 0)
                except ValueError:
                    store.min_stock = 0
            elif prefix == "notes":
                store.notes = (value or "").strip()

        db.session.commit()
        log_event(
            action="stores_template_updated",
            message=f"{t('parts_room')} updated for template {template.name}",
            user=current_user(),
        )
        flash(f"{t('parts_room')} updated for this engine template.", "success")
        return redirect(url_for("stores.stores_for_template", template_id=template.id))

    return render_template(
        "stores.html",
        view_mode="template",
        template=template,
        items=items,
    )


@stores_bp.route("/admin/stores/update", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.STORES.value)
def stores_update():
    view = request.form.get("view", "master")
    org_id = get_org_filter()

    for key, value in request.form.items():
        if "_" not in key:
            continue

        prefix, raw_id = key.split("_", 1)
        if prefix not in {"bin", "stock", "min_stock", "notes"}:
            continue

        try:
            store_id = int(raw_id)
        except ValueError:
            continue

        store = _store_item_for_org(org_id, store_id)
        if not store:
            continue

        if prefix == "bin":
            store.bin_location = (value or "").strip()
        elif prefix == "stock":
            try:
                store.qty_in_stock = int(value or 0)
            except ValueError:
                store.qty_in_stock = 0
        elif prefix == "min_stock":
            try:
                store.min_stock = int(value or 0)
            except ValueError:
                store.min_stock = 0
        elif prefix == "notes":
            store.notes = (value or "").strip()

        if hasattr(StoreItem, "is_consumable"):
            store.is_consumable = f"consumable_{store_id}" in request.form

    db.session.commit()
    log_event(
        action="stores_master_updated",
        message=f"{t('parts_room')} master updated (view={view})",
        user=current_user(),
    )
    flash(f"{t('parts_room')} updated.", "success")
    return redirect(url_for("stores.stores_hub", view=view))


@stores_bp.route("/stores/barcodes/update", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.STORES.value)
def stores_barcodes_update():
    org_id = get_org_filter()
    updated = 0
    cleared = 0
    conflicts = 0
    missing = 0

    for key, value in request.form.items():
        if not key.startswith("barcode_"):
            continue

        raw_id = key.split("_", 1)[1]
        try:
            store_id = int(raw_id)
        except ValueError:
            continue

        store = _store_item_for_org(org_id, store_id)
        if not store:
            missing += 1
            continue

        barcode = (value or "").strip()
        if barcode == "":
            if store.barcode:
                store.barcode = None
                cleared += 1
            continue

        existing = (
            _store_item_query_for_org(org_id)
            .filter(StoreItem.barcode == barcode, StoreItem.id != store.id)
            .first()
        )
        if existing:
            conflicts += 1
            continue

        if store.barcode != barcode:
            store.barcode = barcode
            updated += 1

    if updated or cleared:
        db.session.commit()
        log_event(
            action="stores_barcodes_updated",
            message=f"Barcodes updated: {updated} set, {cleared} cleared, {conflicts} conflicts, {missing} missing.",
            user=current_user(),
        )

    flash(
        f"Barcodes updated: {updated} set, {cleared} cleared, {conflicts} conflicts, {missing} missing.",
        "success" if conflicts == 0 else "warning",
    )
    return redirect(url_for("stores.stores_hub", view="barcodes"))


@stores_bp.route("/stores/barcodes/import", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.STORES.value)
def stores_barcodes_import():
    org_id = get_org_filter()
    csv_file = request.files.get("barcode_csv")
    if not csv_file or not csv_file.filename:
        flash("Please choose a CSV file to import.", "danger")
        return redirect(url_for("stores.stores_hub", view="barcodes"))

    try:
        raw = csv_file.stream.read().decode("utf-8-sig")
    except Exception:
        flash("Unable to read CSV file. Please upload a UTF-8 CSV.", "danger")
        return redirect(url_for("stores.stores_hub", view="barcodes"))

    reader = csv.DictReader(StringIO(raw))
    if not reader.fieldnames:
        flash("CSV has no headers. Expected: part_no, barcode.", "danger")
        return redirect(url_for("stores.stores_hub", view="barcodes"))

    updated = 0
    missing = 0
    conflicts = 0
    duplicates = 0

    for row in reader:
        part_no = (row.get("part_no") or row.get("part_number") or "").strip()
        barcode = (row.get("barcode") or row.get("code") or "").strip()
        if not part_no or not barcode:
            continue

        items = _store_item_query_for_org(org_id).filter(TemplateItem.part_no == part_no).all()

        if not items:
            missing += 1
            continue

        if len(items) > 1:
            duplicates += 1
            continue

        store = items[0]
        existing = (
            _store_item_query_for_org(org_id)
            .filter(StoreItem.barcode == barcode, StoreItem.id != store.id)
            .first()
        )
        if existing:
            conflicts += 1
            continue

        if store.barcode != barcode:
            store.barcode = barcode
            updated += 1

    if updated:
        db.session.commit()
        log_event(
            action="stores_barcodes_import",
            message=f"CSV import: {updated} updated, {missing} missing, {duplicates} duplicate part numbers, {conflicts} conflicts.",
            user=current_user(),
        )

    flash(
        f"CSV import: {updated} updated, {missing} missing, {duplicates} duplicate part numbers, {conflicts} barcode conflicts.",
        "success" if conflicts == 0 else "warning",
    )
    return redirect(url_for("stores.stores_hub", view="barcodes"))


@stores_bp.route("/stores/picklists/<int:picklist_id>/status", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.STORES.value, RoleEnum.OFFICE.value)
def update_picklist_status(picklist_id):
    action = request.form.get("action")
    picklist = _get_picklist_or_404(picklist_id)

    if action == "picked":
        picklist.status = PickListStatusEnum.PICKED
    elif action == "complete":
        picklist.status = PickListStatusEnum.COMPLETE
    else:
        flash("Unknown action for pick list.", "danger")
        return redirect(url_for("stores.stores_hub", view="picklists"))

    synced = _sync_parts_for_picklist(picklist, action or "")
    log_event(
        action="picklist_status",
        message=f"Pick list #{picklist.id} marked {picklist.status.value}.",
        job=picklist.job,
        user=current_user(),
    )
    if synced:
        log_event(
            action="picklist_parts_synced",
            message=f"Pick list #{picklist.id} sync updated {synced} part line(s) ({action}).",
            job=picklist.job,
            user=current_user(),
        )
    db.session.commit()
    flash(f"Pick list #{picklist.id} marked {picklist.status.value}.", "success")
    return redirect(url_for("stores.stores_hub", view="picklists"))


def _lookup_store_item(job: Job, pli: PickListItem, for_update: bool = False):
    if not job or not job.template_id:
        return None
    query = (
        StoreItem.query
        .join(TemplateItem, StoreItem.template_item_id == TemplateItem.id)
        .filter(
            StoreItem.organization_id == job.organization_id,
            TemplateItem.template_id == job.template_id,
            TemplateItem.part_no == pli.part_no,
        )
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _sync_parts_for_picklist(picklist: PickList, action: str) -> int:
    job = picklist.job
    if not job:
        return 0

    parts = PartRequirement.query.filter_by(job_id=job.id).all()
    parts_by_no = {}
    for part in parts:
        key = (part.part_no or "").strip().lower()
        if key:
            parts_by_no.setdefault(key, []).append(part)

    updated = 0
    for pli in picklist.items:
        key = (pli.part_no or "").strip().lower()
        if not key:
            continue
        for part in parts_by_no.get(key, []):
            if action == "picked":
                if part.stock_status == StockStatusEnum.RECEIVED:
                    part.stock_status = StockStatusEnum.IN_STOCK
                    updated += 1
            elif action == "complete":
                if part.stock_status in {StockStatusEnum.IN_STOCK, StockStatusEnum.RECEIVED}:
                    part.stock_status = StockStatusEnum.FITTED
                    updated += 1

    return updated


@stores_bp.route("/stores/picklists/<int:picklist_id>", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.STORES.value, RoleEnum.OFFICE.value)
def picklist_detail(picklist_id):
    picklist = _get_picklist_or_404(picklist_id)
    job = picklist.job
    per_page = parse_int(request.args.get("per_page"), current_app.config.get("PICKLIST_PAGE_SIZE", 50))
    per_page = max(1, min(per_page, current_app.config.get("PICKLIST_PAGE_MAX", 200)))
    page = parse_int(request.args.get("page"), 1)
    if page < 1:
        page = 1

    if request.method == "POST":
        if is_job_locked(job, current_user()):
            flash("Job is complete and read-only. Admin can reopen if needed.", "warning")
            return redirect(url_for("stores.picklist_detail", picklist_id=picklist.id))
        action = (request.form.get("action") or "").strip()
        next_url = (request.form.get("next") or "").strip()
        prefixes = ("picked_", "issued_", "returned_")
        selected_ids = {
            int(v)
            for v in request.form.getlist("select_item")
            if v.isdigit()
        }
        if action in {"bulk_pick", "bulk_clear"} and selected_ids:
            item_ids = selected_ids
        else:
            item_ids = {
                int(key.split("_", 1)[1])
                for key in request.form.keys()
                if key.startswith(prefixes) and key.split("_", 1)[1].isdigit()
            }
        items = (
            PickListItem.query
            .filter(
                PickListItem.pick_list_id == picklist.id,
                PickListItem.organization_id == picklist.organization_id,
                PickListItem.id.in_(item_ids),
            )
            .all()
        )
        for pli in items:
            picked_val = request.form.get(f"picked_{pli.id}")
            issued_raw = (request.form.get(f"issued_{pli.id}") or "").strip()
            returned_raw = (request.form.get(f"returned_{pli.id}") or "").strip()

            old_issued = pli.issued_qty or 0
            old_returned = pli.returned_qty or 0

            if action == "bulk_pick":
                pli.picked = True
            elif action == "bulk_clear":
                pli.picked = False
            else:
                pli.picked = picked_val == "on"
            try:
                if action == "bulk_pick" and not issued_raw:
                    new_issued = pli.qty_required or 0
                elif pli.picked and issued_raw == "":
                    new_issued = pli.qty_required or 0
                else:
                    new_issued = int(issued_raw) if issued_raw != "" else old_issued
            except ValueError:
                new_issued = old_issued
            try:
                new_returned = int(returned_raw) if returned_raw != "" else old_returned
            except ValueError:
                new_returned = old_returned

            issue_delta = new_issued - old_issued
            return_delta = new_returned - old_returned

            pli.issued_qty = new_issued
            pli.returned_qty = new_returned

            if issue_delta or return_delta:
                # Lock the row to prevent concurrent stock mutations
                store_item = _lookup_store_item(job, pli, for_update=True)
                if store_item:
                    if issue_delta:
                        store_item.qty_in_stock = max(0, (store_item.qty_in_stock or 0) - issue_delta)
                    if return_delta:
                        store_item.qty_in_stock = (store_item.qty_in_stock or 0) + return_delta

        all_items = PickListItem.query.filter_by(
            pick_list_id=picklist.id,
            organization_id=picklist.organization_id,
        ).all()
        if all_items and all(item.picked for item in all_items):
            if all(item.issued_qty >= (item.qty_required or 0) for item in all_items):
                picklist.status = PickListStatusEnum.COMPLETE
            else:
                picklist.status = PickListStatusEnum.PICKED
            if picklist.status == PickListStatusEnum.COMPLETE:
                log_event(
                    action="picklist_complete_ready_for_build",
                    message=f"Pick list #{picklist.id} complete. Job ready for rebuild.",
                    job=job,
                    user=current_user(),
                )
                if job.status not in {JobStatusEnum.BUILD, JobStatusEnum.COMPLETE}:
                    try:
                        change_job_status(job, JobStatusEnum.BUILD, user=current_user(), reason="Pick list complete")
                    except InvalidJobTransition as exc:
                        flash(str(exc), "danger")
                        return redirect(url_for("stores.picklist_detail", picklist_id=picklist.id))

        log_event(
            action="picklist_updated",
            message=f"Pick list #{picklist.id} updated",
            job=job,
            user=current_user(),
        )
        bump_revision(job, "stores_picklist_updated", user=current_user())
        db.session.commit()
        flash("Pick list updated.", "success")
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("stores.picklist_detail", picklist_id=picklist.id))

    # Build view model
    total = PickListItem.query.filter_by(
        pick_list_id=picklist.id,
        organization_id=picklist.organization_id,
    ).count()
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    if page > total_pages:
        page = total_pages
    items = (
        PickListItem.query
        .filter_by(
            pick_list_id=picklist.id,
            organization_id=picklist.organization_id,
        )
        .order_by(PickListItem.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    view_items = []
    for pli in items:
        store_item = _lookup_store_item(job, pli)
        view_items.append({
            "id": pli.id,
            "part_no": pli.part_no,
            "name": pli.name,
            "bin": store_item.bin_location if store_item else "",
            "qty": pli.qty_required or 0,
            "picked": pli.picked,
            "issued_qty": pli.issued_qty or 0,
            "returned_qty": pli.returned_qty or 0,
            "stock": store_item.qty_in_stock if store_item else None,
        })

    return render_template(
        "pick_list.html",
        picklist=picklist,
        job=job,
        read_only=is_job_locked(job, current_user()),
        pick_items=view_items,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total=total,
    )
