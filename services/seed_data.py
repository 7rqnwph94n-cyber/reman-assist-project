import os
import random
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

from models import (
    db,
    Organization,
    User,
    Job,
    Template,
    TemplateItem,
    SurveyItem,
    PartRequirement,
    Attachment,
    AuditLog,
    PreSurveyResult,
    RoleEnum,
    JobStatusEnum,
    DecisionEnum,
    StockStatusEnum,
    MeasurementResultEnum,
)
from services.job_services import log_event, ensure_survey_from_template
from utils.localization import t


DEFAULT_USERS = [
    ("technician@example.com", RoleEnum.TECHNICIAN),
    ("office@example.com", RoleEnum.OFFICE),
    ("stores@example.com", RoleEnum.STORES),
    ("admin@example.com", RoleEnum.ADMIN),
]


def _now():
    return datetime.now(timezone.utc)


def _make_job_number(idx: int) -> str:
    return f"JOB-{idx:04d}"


def _pick(seq, rng):
    return seq[rng.randrange(0, len(seq))]


def seed_database(
    users: int = 4,
    templates: int = 5,
    jobs: int = 50,
    items_per_template: int = 80,
    bom_lines_per_job: int = 120,
    with_attachments: bool = False,
    upload_folder: str | None = None,
    password: str = "Password123!",
    seed: int = 1337,
):
    """
    Deterministic data seeding for tests and demos.
    """
    rng = random.Random(seed)
    org = Organization.query.filter_by(slug="global-reman").first()
    if not org:
        org = Organization(
            name="Global Reman",
            slug="global-reman",
        )
        db.session.add(org)
        db.session.flush()

    # Users
    user_map = {}
    for username, role in DEFAULT_USERS[: max(1, users)]:
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(
                username=username,
                role=role,
                password_hash=generate_password_hash(password),
                organization_id=org.id,
            )
            db.session.add(user)
        user_map[role.value] = user
    db.session.flush()

    # Templates + items
    template_list = []
    sections = ["TA", "MAN", "OIL", "COOL", "FUEL"]
    for t_idx in range(1, templates + 1):
        name = f"Template {t_idx}"
        template = Template.query.filter_by(name=name).first()
        if not template:
            template = Template(
                name=name,
                engine_type=f"EngineType-{t_idx}",
                version=1,
                pre_survey_schema='[{"label": "Cleaned", "type": "checkbox"}]',
                organization_id=org.id,
            )
            db.session.add(template)
            db.session.flush()

            for i in range(1, items_per_template + 1):
                section = sections[(i - 1) % len(sections)]
                part_no = f"P{t_idx:02d}-{i:04d}"
                item = TemplateItem(
                    template_id=template.id,
                    organization_id=org.id,
                    section=section,
                    pos=i,
                    part_no=part_no,
                    name=f"Part {part_no}",
                    qty=1,
                    always_replace=(i % 10 == 0),
                    in_kit=(i % 15 == 0),
                    big_ticket=(i % 17 == 0),
                    requires_test=(i % 13 == 0),
                    requires_measurement=(i % 5 == 0),
                    measurement_min=10.0 if i % 5 == 0 else None,
                    measurement_max=20.0 if i % 5 == 0 else None,
                    measurement_unit="mm" if i % 5 == 0 else None,
                )
                db.session.add(item)
        template_list.append(template)
    db.session.flush()

    # Jobs + survey items
    office_user = user_map.get(RoleEnum.OFFICE.value)
    tech_user = user_map.get(RoleEnum.TECHNICIAN.value)
    admin_user = user_map.get(RoleEnum.ADMIN.value)

    for j_idx in range(1, jobs + 1):
        job_number = _make_job_number(j_idx)
        if Job.query.filter_by(job_number=job_number).first():
            continue
        template = _pick(template_list, rng)
        job = Job(
            job_number=job_number,
            job_pack_id=job_number,
            organization_id=org.id,
            customer_name=f"Customer {j_idx}",
            engine_type=template.engine_type,
            serial_number=f"SN-{j_idx:06d}",
            status=_pick(
                [JobStatusEnum.PRE_SURVEY, JobStatusEnum.SURVEY, JobStatusEnum.OFFICE, JobStatusEnum.BUILD],
                rng,
            ),
            template_id=template.id,
            template_version=template.version,
            assigned_to_id=tech_user.id if tech_user else None,
            created_by_id=office_user.id if office_user else None,
            created_at=_now(),
        )
        db.session.add(job)
        db.session.flush()

        ensure_survey_from_template(job)
        survey_items = SurveyItem.query.filter_by(job_id=job.id).all()

        for si in survey_items:
            if si.always_replace:
                si.decision = DecisionEnum.REPLACE
            else:
                si.decision = _pick(
                    [DecisionEnum.REUSE, DecisionEnum.REPLACE, DecisionEnum.SCRAP],
                    rng,
                )
            if si.requires_measurement:
                si.measurement_value = "15.0"
                si.measurement_unit = si.measurement_unit or "mm"
                si.spec_min = si.spec_min or "10.0"
                si.spec_max = si.spec_max or "20.0"
                si.measurement_result = MeasurementResultEnum.WITHIN_SPEC

        # Some jobs are completed
        if j_idx % 4 == 0:
            job.status = JobStatusEnum.OFFICE
            job.survey_version = (job.survey_version or 0) + 1

        # Pre-survey entry for some jobs
        if j_idx % 3 == 0:
            pre = PreSurveyResult(
                job_id=job.id,
                data='{"Cleaned": true}',
                notes="Seeded pre-survey",
                completed_at=_now(),
            )
            db.session.add(pre)

        log_event("job_seeded", f"Seeded job {job_number}", job=job, user=office_user)

    db.session.commit()

    # Build BOM lines for all jobs
    jobs_for_bom = Job.query.order_by(Job.id).all()
    for job in jobs_for_bom:
        survey_items = SurveyItem.query.filter_by(job_id=job.id).all()
        created = 0
        for si in survey_items:
            if not (si.always_replace or si.decision in (DecisionEnum.REPLACE, DecisionEnum.SCRAP)):
                continue
            pr = PartRequirement(
                job_id=job.id,
                survey_item_id=si.id,
                section=si.section,
                pos=si.pos,
                part_no=si.part_no,
                name=si.name,
                qty_required=si.qty or 1,
                stock_status=_pick(
                    [
                        StockStatusEnum.TO_ORDER,
                        StockStatusEnum.ORDERED,
                        StockStatusEnum.RECEIVED,
                        StockStatusEnum.IN_STOCK,
                    ],
                    rng,
                ),
            )
            db.session.add(pr)
            created += 1
            if created >= bom_lines_per_job:
                break
        job.parts_version = (job.parts_version or 0) + 1
        log_event("bom_seeded", f"Seeded {t('parts_list')} ({created} lines)", job=job, user=office_user)
    db.session.commit()

    # Attachments (placeholder files)
    if with_attachments and upload_folder:
        upload_root = Path(upload_folder)
        upload_root.mkdir(parents=True, exist_ok=True)
        jobs_for_att = Job.query.order_by(Job.id).limit(max(1, jobs // 3)).all()
        for job in jobs_for_att:
            rel_dir = upload_root / str(job.id)
            rel_dir.mkdir(parents=True, exist_ok=True)
            filename = f"seed_{job.job_number}.txt"
            path = rel_dir / filename
            path.write_text("Seed attachment", encoding="utf-8")
            rel_path = str(path.relative_to(upload_root))
            att = Attachment(
                job_id=job.id,
                filename=filename,
                original_filename=filename,
                file_path=rel_path,
                file_type="text/plain",
                uploaded_by_id=admin_user.id if admin_user else None,
            )
            db.session.add(att)
            log_event("attachment_seeded", f"Seeded attachment {filename}", job=job, user=admin_user)
        db.session.commit()

    # Basic audit logs for users
    for role_name, user in user_map.items():
        if user:
            log = AuditLog(
                action="seed_user",
                message=f"Seeded user {user.username} ({role_name})",
                user_id=user.id,
                created_at=_now(),
            )
            db.session.add(log)
    db.session.commit()
