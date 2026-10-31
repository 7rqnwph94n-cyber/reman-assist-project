from __future__ import annotations

import os
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

from flask import current_app, url_for

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from models import (
    db,
    Job,
    SurveyItem,
    PartRequirement,
    Attachment,
    AuditLog,
    JobReportRevisionLog,
    MeasurementResultEnum,
    JobStatusEnum,
    CostingSheet,
    CostingLine,
    ErrorLog,
)


def _parse_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        return float(str(val).strip())
    except (TypeError, ValueError):
        return None


def _decision_label(item: SurveyItem) -> str:
    if not item.decision:
        return "—"
    return item.decision.value.replace("_", " ").title()


def _measurement_status(item: SurveyItem) -> str:
    if item.measurement_result == MeasurementResultEnum.WITHIN_SPEC:
        return "within_spec"
    if item.measurement_result == MeasurementResultEnum.OUT_OF_SPEC:
        return "out_of_spec"
    if item.measurement_result == MeasurementResultEnum.NOT_MEASURED:
        return "not_measured"
    val = _parse_float(item.measurement_value)
    min_val = _parse_float(item.spec_min)
    max_val = _parse_float(item.spec_max)
    if val is None or (min_val is None and max_val is None):
        return "not_measured"
    if min_val is not None and val < min_val:
        return "out_of_spec"
    if max_val is not None and val > max_val:
        return "out_of_spec"
    return "within_spec"


def _is_image_attachment(att: Attachment) -> bool:
    ext = (att.filename or "").lower()
    return ext.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def _audit_timeline(job_id: int, limit: int = 40) -> list[AuditLog]:
    key_actions = {
        "job_created",
        "pre_survey_completed",
        "survey_completed",
        "survey_saved",
        "bom_generated",
        "status_change",
        "status_override",
        "attachment_uploaded",
        "release_signed",
        "build_note",
        "login",
    }
    logs = (
        AuditLog.query.filter_by(job_id=job_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    filtered = [l for l in logs if l.action in key_actions]
    return filtered or logs


def _summary_timeline(logs: list[AuditLog]) -> list[AuditLog]:
    return logs[:10]


def _find_user_for_action(logs: list[AuditLog], action: str) -> str:
    for log in logs:
        if log.action == action and log.user:
            return log.user.username
    return "—"


def _find_status_user(logs: list[AuditLog], status_value: str) -> str:
    for log in logs:
        if log.action == "status_change" and status_value in (log.message or "").lower():
            if log.user:
                return log.user.username
    return "—"


def _lock_time(job: Job, logs: list[AuditLog]) -> datetime | None:
    if job.status in {JobStatusEnum.OFFICE, JobStatusEnum.BUILD, JobStatusEnum.COMPLETE}:
        for log in reversed(logs):
            msg = (log.message or "").lower()
            if "to office" in msg or "to build" in msg:
                return log.created_at
        return job.updated_at
    return None


def _part_group_label(part: PartRequirement) -> str:
    item = part.survey_item
    if item and item.always_replace:
        return "100%"
    if item and item.big_ticket:
        return "Big Tkt"
    if item and item.requires_test:
        return "Test"
    return "Standard"


def _part_sort_key(part: PartRequirement) -> tuple[int, int]:
    pos = part.pos if part.pos is not None else 10**9
    return (pos, part.id)


from sqlalchemy.orm import selectinload

def build_job_pack_context(
    job_id: int,
    view_mode: str = "internal",
    requested_by: str | None = None,
) -> dict[str, Any]:
    job = (
        Job.query.options(
            selectinload(Job.survey_items),
            selectinload(Job.part_requirements),
            selectinload(Job.attachments),
            selectinload(Job.audit_logs),
            selectinload(Job.revisions),
        )
        .filter_by(id=job_id)
        .first()
    )
    if not job:
        raise ValueError("Job not found")

    survey_items = sorted(
        job.survey_items, key=lambda s: (s.section, s.pos, s.id)
    )
    parts = sorted(
        job.part_requirements, key=lambda p: (p.pos if p.pos is not None else float("inf"), p.id)
    )
    attachments = sorted(
        job.attachments, key=lambda a: a.uploaded_at, reverse=True
    )

    audit_logs = sorted(
        job.audit_logs, key=lambda log: log.created_at, reverse=True
    )
    revision_logs = sorted(
        job.revisions, key=lambda r: r.created_at, reverse=True
    )

    survey_sections: dict[str, list[SurveyItem]] = defaultdict(list)
    for item in survey_items:
        section = (item.section or "General").strip() or "General"
        survey_sections[section].append(item)

    measurements = []
    out_of_spec = []
    for item in survey_items:
        if not (item.requires_measurement or item.measurement_value or item.spec_min or item.spec_max):
            continue
        status = _measurement_status(item)
        entry = {
            "section": item.section or "General",
            "part_no": item.part_no or "—",
            "name": item.name or "Item",
            "value": item.measurement_value or "—",
            "unit": item.measurement_unit or "",
            "min": item.spec_min or "—",
            "max": item.spec_max or "—",
            "status": status,
        }
        measurements.append(entry)
        if status == "out_of_spec":
            out_of_spec.append(entry)

    parts_by_group: dict[str, list[PartRequirement]] = defaultdict(list)
    for part in parts:
        parts_by_group[_part_group_label(part)].append(part)

    group_order = ["100%", "Big Tkt", "Standard", "Test"]
    parts_groups = []
    for label in group_order:
        items = sorted(parts_by_group.get(label, []), key=_part_sort_key)
        if items:
            parts_groups.append(SimpleNamespace(label=label, parts=items))

    report_incomplete = False
    report_errors: list[str] = []
    cost_by_part_id = {}
    total_cost = Decimal("0")
    sheet = CostingSheet.query.filter_by(job_id=job.id).first()
    if sheet:
        lines = CostingLine.query.filter_by(costing_sheet_id=sheet.id).all()
        for line in lines:
            if not line.part_requirement_id:
                continue
            cost_val = line.unit_cost_confirmed or line.latest_cost or line.price_cost
            cost_by_part_id[line.part_requirement_id] = cost_val
            if cost_val is not None:
                try:
                    qty = Decimal(str(line.qty_required or 0))
                    total_cost += Decimal(str(cost_val)) * qty
                except (InvalidOperation, TypeError):
                    report_incomplete = True
                    report_errors.append(
                        f"Costing parse failed for part_requirement_id={line.part_requirement_id}"
                    )

    attachments_list = []
    embed_images = bool(current_app.config.get("REPORT_EMBED_IMAGES"))
    if view_mode != "internal":
        embed_images = False
    max_images = int(current_app.config.get("REPORT_MAX_IMAGE_EMBEDS", 6))
    max_embed_bytes = int(current_app.config.get("REPORT_MAX_IMAGE_EMBED_MB", 5)) * 1024 * 1024
    image_count = 0
    embed_bytes = 0
    suppressed_images = 0
    for att in attachments:
        file_path = att.file_path or att.filename
        file_url = url_for("uploaded_file", filename=file_path) if file_path else None
        is_image = _is_image_attachment(att)
        include_thumb = False
        if embed_images and is_image and image_count < max_images and file_path:
            abs_path = current_app.config.get("UPLOAD_FOLDER")
            if abs_path:
                full_path = os.path.join(abs_path, file_path)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0
                if embed_bytes + size <= max_embed_bytes:
                    include_thumb = True
                    image_count += 1
                    embed_bytes += size
                else:
                    suppressed_images += 1
            else:
                include_thumb = True
                image_count += 1
        elif is_image and embed_images:
            suppressed_images += 1
        attachments_list.append(
            {
                "filename": att.original_filename or att.filename,
                "file_type": att.file_type or "—",
                "uploaded_by": att.uploaded_by.username if att.uploaded_by else "—",
                "uploaded_at": att.uploaded_at,
                "file_url": file_url,
                "is_image": is_image,
                "include_thumb": include_thumb,
            }
        )

    totals = {
        "survey_total": len(survey_items),
        "survey_big_ticket": len([s for s in survey_items if getattr(s, "big_ticket", False)]),
        "survey_out_of_spec": len(out_of_spec),
        "parts_total": len(parts),
        "attachments_total": len(attachments),
    }

    presurvey = getattr(job, "pre_survey_result", None)
    presurvey_data = {}
    presurvey_notes = None
    presurvey_completed_at = None
    presurvey_photo_url = None
    if presurvey:
        presurvey_notes = presurvey.notes
        presurvey_completed_at = presurvey.completed_at
        if presurvey.data:
            try:
                import json

                presurvey_data = json.loads(presurvey.data) or {}
            except Exception:
                report_incomplete = True
                report_errors.append("Pre-survey data could not be parsed.")
                presurvey_data = {}
        if presurvey.thumbnail_path:
            presurvey_photo_url = url_for("uploaded_file", filename=presurvey.thumbnail_path)

    audit_logs = _audit_timeline(job.id)
    revision_logs = (
        JobReportRevisionLog.query.filter_by(job_id=job.id)
        .order_by(JobReportRevisionLog.created_at.desc())
        .limit(50)
        .all()
    )
    lock_time = _lock_time(job, audit_logs)
    edits_after_lock = []
    if lock_time:
        edits_after_lock = [r for r in revision_logs if r.created_at and r.created_at > lock_time][:5]

    who_did_what = {
        "created_by": job.created_by.username if job.created_by else "—",
        "survey_by": _find_user_for_action(audit_logs, "survey_completed"),
        "bom_by": _find_user_for_action(audit_logs, "survey_completed"),
        "stores_by": _find_user_for_action(audit_logs, "picklist_updated"),
        "completed_by": _find_status_user(audit_logs, "complete"),
    }

    context = {
        "job": job,
        "template": job.template,
        "survey_sections": dict(sorted(survey_sections.items())),
        "survey_items": survey_items,
        "parts_groups": parts_groups,
        "parts": parts,
        "cost_by_part_id": cost_by_part_id,
        "parts_cost_total": float(total_cost) if total_cost else None,
        "measurements": measurements,
        "out_of_spec": out_of_spec,
        "attachments": attachments_list,
        "audit_logs": audit_logs,
        "summary_timeline": _summary_timeline(audit_logs),
        "totals": totals,
        "presurvey_data": presurvey_data,
        "presurvey_notes": presurvey_notes,
        "presurvey_completed_at": presurvey_completed_at,
        "presurvey_photo_url": presurvey_photo_url,
        "decision_label": _decision_label,
        "generated_at": datetime.now(timezone.utc),
        "generated_by": requested_by or "—",
        "view_mode": view_mode,
        "revision": job.report_revision or 0,
        "revision_logs": revision_logs,
        "edits_after_lock": edits_after_lock,
        "lock_time": lock_time,
        "who_did_what": who_did_what,
        "suppressed_images": suppressed_images if embed_images else 0,
        "report_incomplete": report_incomplete,
        "report_errors": report_errors,
    }
    return context
    if report_incomplete:
        try:
            db.session.add(
                ErrorLog(
                    path=f"job_report:{job.id}",
                    message="REPORT INCOMPLETE: " + "; ".join(report_errors),
                    user_id=None,
                )
            )
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
