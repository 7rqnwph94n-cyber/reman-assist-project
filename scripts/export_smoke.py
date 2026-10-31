#!/usr/bin/env python3
"""
Export smoke test for pilot gate.
Generates both PDF and ZIP artifacts and fails loudly if renderer deps are missing.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import render_template
from werkzeug.security import generate_password_hash

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import create_app
from models import (
    db,
    Job,
    JobStatusEnum,
    Organization,
    RoleEnum,
    Template,
    TemplateItem,
    User,
)
from services.job_pack_export import build_job_pack_zip
from services.job_pack_report import build_job_pack_context
from services.pdf_renderer import get_pdf_renderer_status, render_report_pdf


def _ensure_smoke_job() -> Job:
    existing = Job.query.order_by(Job.id.asc()).first()
    if existing:
        return existing

    org = Organization.query.order_by(Organization.id.asc()).first()
    if not org:
        org = Organization(name="Smoke Org", slug="smoke-org")
        db.session.add(org)
        db.session.flush()

    office_user = User.query.filter_by(organization_id=org.id, role=RoleEnum.OFFICE).first()
    if not office_user:
        office_user = User(
            username="smoke.office@example.com",
            password_hash=generate_password_hash("Password123!"),
            role=RoleEnum.OFFICE,
            organization_id=org.id,
        )
        db.session.add(office_user)
        db.session.flush()

    template = Template.query.filter_by(organization_id=org.id).first()
    if not template:
        template = Template(name="Smoke Template", engine_type="smoke", organization_id=org.id)
        db.session.add(template)
        db.session.flush()
        db.session.add(
            TemplateItem(
                template_id=template.id,
                organization_id=org.id,
                section="A",
                pos=1,
                part_no="SMOKE-001",
                name="Smoke Part",
                qty=1,
            )
        )

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    job = Job(
        organization_id=org.id,
        job_pack_id=f"SMOKE-{stamp}",
        job_number=f"SMOKE-{stamp}",
        template_id=template.id,
        created_by_id=office_user.id,
        status=JobStatusEnum.PRE_SURVEY,
    )
    db.session.add(job)
    db.session.commit()
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate export smoke artifacts")
    parser.add_argument("--output-dir", default="/tmp/reman_export_smoke", help="Destination directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    app = create_app()
    with app.app_context():
        app.config["REPORT_BASE_URL"] = f"file://{app.root_path}/"
        renderer = get_pdf_renderer_status()
        print(f"PDF_RENDERER_STATUS={renderer}")
        if not renderer.get("ready"):
            print("FAIL: No PDF renderer available for pilot export")
            return 1

        job = _ensure_smoke_job()
        css_path = os.path.join(app.root_path, "static", "css", "report.css")

        with app.test_request_context("/"):
            context = build_job_pack_context(job.id, view_mode="internal")
            html = render_template("reports/job_pack_report.html", **context)
            pdf_bytes = render_report_pdf(
                html,
                base_url=app.config["REPORT_BASE_URL"],
                css_path=css_path,
            )
            zip_bytes = build_job_pack_zip(job, view_mode="internal")

        pdf_path = output_dir / f"{job.job_number}_smoke_report.pdf"
        zip_path = output_dir / f"{job.job_number}_smoke_export.zip"
        pdf_path.write_bytes(pdf_bytes)
        zip_path.write_bytes(zip_bytes)

        if pdf_path.stat().st_size <= 0:
            print(f"FAIL: Empty PDF output: {pdf_path}")
            return 1
        if zip_path.stat().st_size <= 0:
            print(f"FAIL: Empty ZIP output: {zip_path}")
            return 1

        print("PASS: export smoke complete")
        print(f"SMOKE_JOB_ID={job.id}")
        print(f"SMOKE_PDF={pdf_path}")
        print(f"SMOKE_ZIP={zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
