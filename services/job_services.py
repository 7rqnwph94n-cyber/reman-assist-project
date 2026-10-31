from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from models import (
    db,
    Job,
    User,
    Template,
    TemplateItem,
    SurveyItem,
    JobStatusEnum,
    RoleEnum,
    AuditLog,
    JobLog,
    PartRequirement,
    StockStatusEnum,
    Attachment,
    PickList,
    MeasurementAuditLog,
    InvalidJobTransition,
)
from services.job_pack_revision import bump_revision
from services.measurement_service import normalize_decimal_field


def log_event(action: str, message: str, job: Job | None = None, user=None, details: str | None = None) -> None:
    """
    Fire-and-forget audit log writer.
    Never raises into the main request flow.
    """
    try:
        entry = AuditLog(
            action=action,
            message=message,
            job_id=job.id if job else None,
            user_id=user.id if user else None,
            details=details,
        )
        db.session.add(entry)
        # Don't commit here – let the caller's db.session.commit() handle it
    except SQLAlchemyError as e:
        # Never break the app because of logging
        from flask import current_app
        if current_app:
            current_app.logger.warning(f"Failed to log audit event '{action}': {e}")


def change_job_status(job: Job, new_status: JobStatusEnum, user=None, reason: str | None = None) -> None:
    """
    Update a job's status and write an audit log entry.
    """
    old_status = job.status
    if isinstance(new_status, JobStatusEnum):
        target_status = new_status
    else:
        target_status = JobStatusEnum(new_status)
    try:
        job.transition_to(target_status)
    except InvalidJobTransition:
        raise

    old_val = getattr(old_status, "value", old_status)
    new_val = getattr(target_status, "value", target_status)

    msg = f"Job status changed from {old_val} to {new_val}"
    if reason:
        msg += f" | Reason: {reason}"

    log_event(
        action="status_change",
        message=msg,
        job=job,
        user=user,
    )
    bump_revision(job, f"status_change:{new_val}", user=user)


def is_job_locked(job: Job, user=None) -> bool:
    """
    Completed jobs are read-only for non-admins.
    """
    if job.status == JobStatusEnum.COMPLETE:
        return not user or user.role != RoleEnum.ADMIN
    return False


def create_job(job_number, customer_name, engine_type, serial_number, template_id, assigned_to_id, user_id):
    """
    Create a new job.
    """
    if not job_number:
        raise ValueError("Job number is required.")

    if not template_id:
        raise ValueError("Template selection is required.")

    user = db.session.get(User, user_id) if user_id else None
    if not user or not user.current_organization_id:
        raise ValueError("Job creator must belong to an organization.")

    existing = Job.query.filter_by(
        organization_id=user.current_organization_id,
        job_number=job_number,
    ).first()
    if existing:
        raise ValueError(f"Job number {job_number} already exists.")

    template_ver = None
    if template_id:
        tmpl = Template.query.filter_by(
            id=int(template_id),
            organization_id=user.current_organization_id,
        ).first()
        if not tmpl:
            raise ValueError("Selected template is not available for this organization.")
        template_ver = tmpl.version if tmpl else None
    job = Job(
        job_number=job_number,
        job_pack_id=job_number,  # keep pack id aligned to job number by default
        customer_name=customer_name or None,
        engine_type=engine_type or None,
        serial_number=serial_number or None,
        status=JobStatusEnum.PRE_SURVEY,
        template_id=int(template_id) if template_id else None,
        template_version=template_ver,
        assigned_to_id=int(assigned_to_id) if assigned_to_id else None,
        created_by_id=user_id if user_id else None,
        organization_id=user.current_organization_id,
    )

    db.session.add(job)
    db.session.flush()
    log_event(
        action="job_created",
        message=f"Job created: {job_number}",
        job=job,
        user=user,
    )
    db.session.commit()
    ensure_survey_from_template(job)
    return job


def get_dashboard_jobs(
    user,
    per_status_limit: int = 25,
    search_query: str | None = None,
    status_filter: JobStatusEnum | None = None,
    sort_by: str | None = None,
):
    """
    Get all jobs for the dashboard, filtered by user role.
    """
    filters = []
    if user and user.current_organization_id:
        filters.append(Job.organization_id == user.current_organization_id)
    if user.role == RoleEnum.TECHNICIAN:
        filters.append(Job.assigned_to_id == user.id)
    if search_query:
        like = f"%{search_query}%"
        filters.append(
            or_(
                Job.job_number.ilike(like),
                Job.job_pack_id.ilike(like),
                Job.customer_name.ilike(like),
                Job.engine_type.ilike(like),
                Job.serial_number.ilike(like),
            )
        )

    status_map = {
        "Pre-survey": JobStatusEnum.PRE_SURVEY,
        "Survey": JobStatusEnum.SURVEY,
        "Office": JobStatusEnum.OFFICE,
        "Build": JobStatusEnum.BUILD,
        "Complete": JobStatusEnum.COMPLETE,
    }

    status_totals = {label: 0 for label in status_map.keys()}
    totals_rows = (
        db.session.query(Job.status, db.func.count(Job.id))
        .filter(*filters)
        .group_by(Job.status)
        .all()
    )
    totals_by_status = {status: count for status, count in totals_rows}
    for label, status in status_map.items():
        status_totals[label] = totals_by_status.get(status, 0)

    jobs_by_status = {label: [] for label in status_map.keys()}
    activity_joins = []
    if sort_by == "updated":
        bind = db.session.get_bind()

        def _greatest(*cols):
            expr = cols[0]
            for col in cols[1:]:
                if bind.dialect.name == "sqlite":
                    expr = db.func.max(expr, col)
                else:
                    expr = db.func.greatest(expr, col)
            return expr

        audit_sq = (
            db.session.query(
                AuditLog.job_id.label("job_id"),
                db.func.max(AuditLog.created_at).label("last_audit"),
            )
            .group_by(AuditLog.job_id)
            .subquery()
        )
        joblog_sq = (
            db.session.query(
                JobLog.job_id.label("job_id"),
                db.func.max(JobLog.timestamp).label("last_joblog"),
            )
            .group_by(JobLog.job_id)
            .subquery()
        )
        part_sq = (
            db.session.query(
                PartRequirement.job_id.label("job_id"),
                db.func.max(PartRequirement.updated_at).label("last_part"),
            )
            .group_by(PartRequirement.job_id)
            .subquery()
        )
        att_sq = (
            db.session.query(
                Attachment.job_id.label("job_id"),
                db.func.max(Attachment.uploaded_at).label("last_attachment"),
            )
            .group_by(Attachment.job_id)
            .subquery()
        )
        pick_sq = (
            db.session.query(
                PickList.job_id.label("job_id"),
                db.func.max(PickList.created_at).label("last_picklist"),
            )
            .group_by(PickList.job_id)
            .subquery()
        )

        activity_joins = [audit_sq, joblog_sq, part_sq, att_sq, pick_sq]
        fallback = db.func.coalesce(Job.updated_at, Job.created_at)
        order_by = _greatest(
            db.func.coalesce(audit_sq.c.last_audit, fallback),
            db.func.coalesce(joblog_sq.c.last_joblog, fallback),
            db.func.coalesce(part_sq.c.last_part, fallback),
            db.func.coalesce(att_sq.c.last_attachment, fallback),
            db.func.coalesce(pick_sq.c.last_picklist, fallback),
            fallback,
        ).desc()
    else:
        order_by = Job.created_at.desc()
    for label, status in status_map.items():
        if status_filter and status != status_filter:
            continue
        query = Job.query
        # Eager load relationships to prevent N+1 queries on dashboard
        query = query.options(
            selectinload(Job.assigned_to),
            selectinload(Job.template),
            selectinload(Job.created_by)
        )
        for sq in activity_joins:
            query = query.outerjoin(sq, Job.id == sq.c.job_id)
        jobs_by_status[label] = (
            query
            .filter(*filters, Job.status == status)
            .order_by(order_by)
            .limit(per_status_limit)
            .all()
        )

    displayed_job_ids = [job.id for jobs in jobs_by_status.values() for job in jobs]

    nc_counts = {}
    procurement_counts = {}
    if displayed_job_ids:
        nc_counts = {}

        rows = (
            db.session.query(PartRequirement.job_id, db.func.count(PartRequirement.id))
            .filter(
                PartRequirement.job_id.in_(displayed_job_ids),
                PartRequirement.stock_status.in_([
                    StockStatusEnum.TO_ORDER,
                    StockStatusEnum.ORDERED,
                    StockStatusEnum.BACKORDER,
                ]),
            )
            .group_by(PartRequirement.job_id)
            .all()
        )
        procurement_counts = {job_id: count for job_id, count in rows}

    return jobs_by_status, nc_counts, procurement_counts, status_totals


def ensure_survey_from_template(job: Job) -> None:
    """
    Ensure this job has SurveyItem rows, seeded from its Template items.

    - If survey items already exist for the job, do nothing.
    - Otherwise, copy all TemplateItem rows over, including behaviour flags.
    """
    existing = SurveyItem.query.filter_by(job_id=job.id).first()
    if existing:
        return

    if not job.template_id:
        return

    template = db.session.get(Template, job.template_id)
    if not template:
        return

    template_items = (
        TemplateItem.query
        .filter_by(template_id=template.id)
        .order_by(TemplateItem.section, TemplateItem.pos)
        .all()
    )

    for t in template_items:
        kit_name = None
        kit_master = False
        if getattr(t, "groups", None):
            for g in t.groups:
                if getattr(g, "type", None) == "kit":
                    kit_name = g.label
                    kit_master = bool(t.in_kit)
                    break

        s = SurveyItem(
            job_id=job.id,
            section=t.section,
            pos=t.pos,
            part_no=t.part_no,
            name=t.name,
            qty=t.qty or 1,
            always_replace=t.always_replace,
            in_kit=t.in_kit,
            big_ticket=getattr(t, "big_ticket", False),
            requires_test=getattr(t, "requires_test", False),
            requires_measurement=t.requires_measurement,
            # Seed measurement specs/units from template so techs see limits
            spec_min=normalize_decimal_field(t.measurement_min)[1] if t.measurement_min is not None else None,
            spec_max=normalize_decimal_field(t.measurement_max)[1] if t.measurement_max is not None else None,
            measurement_unit=t.measurement_unit,
            kit_name=kit_name,
            kit_master=kit_master,
        )
        db.session.add(s)

    db.session.commit()


def get_measurement_audit_for_job(job_id: int):
    """
    Return measurement audit history for a job (newest first).
    """
    return (
        MeasurementAuditLog.query
        .join(SurveyItem, MeasurementAuditLog.survey_item_id == SurveyItem.id)
        .filter(SurveyItem.job_id == job_id)
        .order_by(MeasurementAuditLog.timestamp.desc())
        .all()
    )
