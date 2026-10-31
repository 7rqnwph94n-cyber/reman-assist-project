from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from typing import Any

from flask import current_app, render_template, request

from models import Job, PartRequirement, Attachment, CostingLine, CostingSheet, AuditLog
from services.job_pack_report import build_job_pack_context
from services.pdf_renderer import render_report_pdf
from utils.localization import t


def _build_bom_csv(job: Job, view_mode: str = "internal") -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    customer_view = view_mode == "customer"
    if customer_view:
        writer.writerow(["Part No", "Description", "Qty", "Status"])
    else:
        writer.writerow(["Section", "Part No", "Description", "Qty", "Status", "Cost", "Notes"])
    parts = (
        PartRequirement.query.filter_by(job_id=job.id)
        .order_by(PartRequirement.section, PartRequirement.pos, PartRequirement.id)
        .all()
    )
    cost_by_part_id = {}
    if not customer_view:
        sheet = CostingSheet.query.filter_by(job_id=job.id).first()
        if sheet:
            lines = CostingLine.query.filter_by(costing_sheet_id=sheet.id).all()
            for line in lines:
                if not line.part_requirement_id:
                    continue
                cost_val = line.unit_cost_confirmed or line.latest_cost or line.price_cost
                cost_by_part_id[line.part_requirement_id] = cost_val
    for part in parts:
        if customer_view:
            writer.writerow(
                [
                    part.part_no or "",
                    part.name or "",
                    part.qty_required or 0,
                    part.stock_status.value if part.stock_status else "",
                ]
            )
        else:
            cost_val = cost_by_part_id.get(part.id)
            writer.writerow(
                [
                    part.section or "",
                    part.part_no or "",
                    part.name or "",
                    part.qty_required or 0,
                    part.stock_status.value if part.stock_status else "",
                    f"{cost_val:.2f}" if cost_val is not None else "",
                    part.notes or "",
                ]
            )
    return output.getvalue()


def _build_attachments_index(attachments: list[Attachment], upload_root: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Stored filename", "Original filename", "Uploaded by", "Uploaded at", "Included"])
    for att in attachments:
        rel = att.file_path or att.filename
        full = os.path.join(upload_root, rel) if rel else ""
        included = "yes" if full and os.path.exists(full) else "no"
        writer.writerow(
            [
                att.filename or "",
                att.original_filename or "",
                att.uploaded_by.username if att.uploaded_by else "",
                att.uploaded_at.isoformat() if att.uploaded_at else "",
                included,
            ]
        )
    return output.getvalue()


def build_job_pack_zip(
    job: Job,
    view_mode: str = "internal",
    include_bom: bool = True,
    requested_by: str | None = None,
) -> bytes:
    context = build_job_pack_context(job.id, view_mode=view_mode, requested_by=requested_by)

    html = render_template("reports/job_pack_report.html", **context)
    css_path = os.path.join(current_app.root_path, "static", "css", "report.css")
    base_url = current_app.config.get("REPORT_BASE_URL") or request.url_root
    pdf_bytes = render_report_pdf(html, base_url, css_path)

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        report_prefix = t("work_order_caps").replace(" ", "")
        report_name = f"{report_prefix}_{job.job_number}_Report.pdf"
        zf.writestr(report_name, pdf_bytes)

        if include_bom:
            bom_csv = _build_bom_csv(job, view_mode=view_mode)
            parts_prefix = t("parts_list_caps").replace(" ", "")
            zf.writestr(f"{parts_prefix}_{job.job_number}.csv", bom_csv)

        attachments = Attachment.query.filter_by(job_id=job.id).all()
        upload_root = current_app.config.get("UPLOAD_FOLDER") or ""
        index_csv = _build_attachments_index(attachments, upload_root)
        zf.writestr("attachments_index.csv", index_csv)

        audit_rows = (
            AuditLog.query.filter_by(job_id=job.id)
            .order_by(AuditLog.created_at.asc())
            .all()
        )
        audit_payload = [
            {
                "action": log.action,
                "message": log.message,
                "user": log.user.username if log.user else "",
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in audit_rows
        ]
        zf.writestr("audit_log.json", json.dumps(audit_payload))
        signoff_payload = {
            "job_number": job.job_number,
            "release_signed_by": job.release_signed_by.username if job.release_signed_by else "",
            "release_signed_at": job.release_signed_at.isoformat() if job.release_signed_at else "",
            "report_revision": context.get("revision") or 0,
        }
        zf.writestr("signoff.json", json.dumps(signoff_payload))

        for att in attachments:
            rel = att.file_path or att.filename
            if not rel:
                continue
            full = os.path.join(upload_root, rel)
            arc = os.path.join("attachments", os.path.basename(rel))
            if os.path.exists(full):
                zf.write(full, arcname=arc)
            else:
                placeholder = f"Missing file: {rel}"
                zf.writestr(f"{arc}.missing.txt", placeholder)

    mem.seek(0)
    return mem.read()
