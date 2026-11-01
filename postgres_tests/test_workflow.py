"""Real PostgreSQL workflow regressions; run only through the dedicated gate."""

import json
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from werkzeug.security import generate_password_hash

from models import (
    db, Organization, User, RoleEnum, Template, TemplateItem, Job, JobStatusEnum,
    SurveyItem, PreSurveyResult, PartRequirement, StockStatusEnum, DecisionEnum,
    AuditLog, JobReportRevisionLog, MeasurementAuditLog, InvalidJobTransition,
)
from services.job_services import change_job_status
from utils.tenant_scope import set_current_org_id


PASSWORD = "PostgresTestOnly123!"


def login(client, user):
    response = client.post("/login", data={"username": user["username"], "password": PASSWORD})
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["user_id"] == user["id"]


def state(job_id):
    queries = {
        "job": Job.query.filter_by(id=job_id),
        "survey": SurveyItem.query.filter_by(job_id=job_id),
        "pre_survey": PreSurveyResult.query.filter_by(job_id=job_id),
        "bom": PartRequirement.query.filter_by(job_id=job_id),
        "audit": AuditLog.query.filter_by(job_id=job_id),
        "revisions": JobReportRevisionLog.query.filter_by(job_id=job_id),
        "measurements": MeasurementAuditLog.query.join(SurveyItem).filter(SurveyItem.job_id == job_id),
    }
    return {name: [
        {column.key: getattr(row, column.key) for column in row.__table__.columns}
        for row in sorted(query.all(), key=lambda row: row.id)
    ] for name, query in queries.items()}


@pytest.fixture
def job_data(postgres_app, client):
    token = uuid4().hex[:12]
    users = {}
    with postgres_app.app_context():
        for label in ("owner", "other"):
            org = Organization(name=f"PG {label} {token}", slug=f"pg-{label}-{token}")
            db.session.add(org)
            db.session.flush()
            users[label] = {}
            for role in RoleEnum:
                user = User(
                    username=f"{label}-{role.name}-{token}@example.com",
                    password_hash=generate_password_hash(PASSWORD),
                    role=role, organization_id=org.id,
                )
                db.session.add(user)
                db.session.flush()
                users[label][role] = {"id": user.id, "username": user.username, "org_id": org.id}
        org_id = users["owner"][RoleEnum.ADMIN]["org_id"]
        template = Template(
            name=f"PG template {token}", engine_type="PG", organization_id=org_id,
            pre_survey_schema=json.dumps([{"label": "Cleaned", "type": "checkbox"}]),
        )
        db.session.add(template)
        db.session.flush()
        for pos, qty in ((1, 2), (2, 1)):
            db.session.add(TemplateItem(
                template_id=template.id, organization_id=org_id,
                section="A", pos=pos, part_no=f"PG-P{pos}", name=f"Part {pos}", qty=qty,
            ))
        db.session.commit()
        template_id = template.id

    login(client, users["owner"][RoleEnum.OFFICE])
    number = f"PG-{token}"
    response = client.post("/jobs/create", data={
        "job_number": number, "template_id": str(template_id),
        "assigned_to_id": str(users["owner"][RoleEnum.TECHNICIAN]["id"]),
        "customer_name": "Disposable PostgreSQL integration",
    })
    assert response.status_code == 302 and response.location == "/jobs"
    with postgres_app.app_context():
        job = Job.query.filter_by(job_number=number, organization_id=org_id).one()
        assert job.status == JobStatusEnum.PRE_SURVEY
        assert job.created_by_id == users["owner"][RoleEnum.OFFICE]["id"]
        assert job.assigned_to_id == users["owner"][RoleEnum.TECHNICIAN]["id"]
        assert SurveyItem.query.filter_by(job_id=job.id).count() == 2
        job_id = job.id
    return {"job_id": job_id, "template_id": template_id, "users": users}


def test_organisations_roles_and_job_creation(postgres_app, job_data):
    with postgres_app.app_context():
        for group in job_data["users"].values():
            for role, details in group.items():
                user = db.session.get(User, details["id"])
                assert user.role == role and user.organization_id == details["org_id"]
        log = AuditLog.query.filter_by(job_id=job_data["job_id"], action="job_created").one()
        assert log.user_id == job_data["users"]["owner"][RoleEnum.OFFICE]["id"]


def test_presurvey_completion_idempotency_bom_and_transitions(postgres_app, client, job_data):
    job_id = job_data["job_id"]
    tech = job_data["users"]["owner"][RoleEnum.TECHNICIAN]
    login(client, tech)
    with postgres_app.app_context():
        before_gate = state(job_id)
        items = SurveyItem.query.filter_by(job_id=job_id).order_by(SurveyItem.pos).all()
        item_ids = [item.id for item in items]
    form = {"action": "complete", "survey_version": "0", "visible_ids": ",".join(map(str, item_ids))}
    form.update({f"decision_{item_id}": "replace" for item_id in item_ids})
    # The obsolete session flag must never bypass the persisted prerequisite.
    with client.session_transaction() as session:
        session[f"pre_survey_done_{job_id}"] = True
    response = client.post(f"/jobs/{job_id}/survey", data=form)
    assert response.status_code == 302 and response.location == f"/jobs/{job_id}/pre_survey"
    with postgres_app.app_context():
        assert state(job_id) == before_gate

    response = client.post(f"/jobs/{job_id}/pre_survey", data={"field_1": "on", "notes": "PG receipt"})
    assert response.status_code == 302 and response.location == f"/jobs/{job_id}/survey"
    assert client.get(f"/jobs/{job_id}/survey").status_code == 200
    with postgres_app.app_context():
        pre = PreSurveyResult.query.filter_by(job_id=job_id).one()
        assert json.loads(pre.data) == {"Cleaned": True}
        assert pre.completed_at is not None and pre.notes == "PG receipt"
        assert db.session.get(Job, job_id).status == JobStatusEnum.SURVEY

    response = client.post(f"/jobs/{job_id}/survey", data=form)
    assert response.status_code == 302 and response.location == f"/jobs/{job_id}/parts"
    with postgres_app.app_context():
        job = db.session.get(Job, job_id)
        assert (job.status, job.survey_version, job.parts_version, job.report_revision) == (
            JobStatusEnum.OFFICE, 1, 0, 3,
        )
        items = SurveyItem.query.filter_by(job_id=job_id).order_by(SurveyItem.pos).all()
        assert [(item.id, item.decision) for item in items] == [(i, DecisionEnum.REPLACE) for i in item_ids]
        parts = PartRequirement.query.filter_by(job_id=job_id).order_by(PartRequirement.pos).all()
        assert [(p.survey_item_id, p.part_no, p.qty_required, p.stock_status) for p in parts] == [
            (item_ids[0], "PG-P1", 2, StockStatusEnum.TO_ORDER),
            (item_ids[1], "PG-P2", 1, StockStatusEnum.TO_ORDER),
        ]
        logs = AuditLog.query.filter_by(job_id=job_id).order_by(AuditLog.id).all()
        assert [(log.action, log.user_id) for log in logs] == [
            ("job_created", job_data["users"]["owner"][RoleEnum.OFFICE]["id"]),
            ("pre_survey_saved", tech["id"]), ("status_change", tech["id"]),
            ("status_change", None), ("survey_completed", tech["id"]),
        ]
        revisions = JobReportRevisionLog.query.filter_by(job_id=job_id).order_by(JobReportRevisionLog.revision).all()
        assert [(r.revision, r.reason, r.user_id) for r in revisions] == [
            (1, "status_change:survey", tech["id"]), (2, "status_change:office", None),
            (3, "survey_completed/bom_generated", tech["id"]),
        ]
        completed = state(job_id)
        assert completed["measurements"] == []
    response = client.post(f"/jobs/{job_id}/survey", data=form)
    assert response.status_code == 302 and urlsplit(response.location).path == f"/jobs/{job_id}/survey"
    with postgres_app.app_context():
        assert state(job_id) == completed
        job = db.session.get(Job, job_id)
        admin = db.session.get(User, job_data["users"]["owner"][RoleEnum.ADMIN]["id"])
        change_job_status(job, JobStatusEnum.BUILD, user=admin)
        db.session.commit()
        build_state = state(job_id)
        with pytest.raises(InvalidJobTransition, match="pending/on order"):
            change_job_status(job, JobStatusEnum.COMPLETE, user=admin)
        db.session.rollback()
        assert state(job_id) == build_state
        for part in PartRequirement.query.filter_by(job_id=job_id).all():
            part.stock_status = StockStatusEnum.RECEIVED
            part.qty_received = part.qty_required
        db.session.commit()
        change_job_status(job, JobStatusEnum.COMPLETE, user=admin)
        db.session.commit()
        assert job.status == JobStatusEnum.COMPLETE and job.report_revision == 5
        assert JobReportRevisionLog.query.filter_by(job_id=job_id).count() == 5
        assert AuditLog.query.filter_by(job_id=job_id, action="status_change").count() == 4


@pytest.mark.parametrize("role", [RoleEnum.OFFICE, RoleEnum.STORES])
def test_roles_cannot_modify_presurvey(postgres_app, client, job_data, role):
    job_id = job_data["job_id"]
    login(client, job_data["users"]["owner"][role])
    with postgres_app.app_context():
        before = state(job_id)
    assert client.post(f"/jobs/{job_id}/pre_survey", data={"field_1": "on"}).status_code == 403
    with postgres_app.app_context():
        assert state(job_id) == before


@pytest.mark.parametrize("role", [RoleEnum.ADMIN, RoleEnum.OFFICE, RoleEnum.TECHNICIAN])
def test_cross_organisation_access_is_rejected(postgres_app, client, job_data, role):
    job_id = job_data["job_id"]
    outsider = job_data["users"]["other"][role]
    login(client, outsider)
    with postgres_app.app_context():
        before = state(job_id)
        set_current_org_id(outsider["org_id"])
        try:
            assert db.session.get(Job, job_id) is None
            assert db.session.get(Template, job_data["template_id"]) is None
        finally:
            set_current_org_id(None)
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/jobs/{job_id}/survey").status_code == 404
    assert client.post(f"/jobs/{job_id}/survey", data={"action": "complete"}).status_code == 404
    with postgres_app.app_context():
        assert state(job_id) == before


def test_postgres_transaction_rollback(postgres_app):
    slug = f"rollback-{uuid4().hex}"
    with postgres_app.app_context():
        db.session.add(Organization(name=slug, slug=slug))
        db.session.flush()
        assert Organization.query.filter_by(slug=slug).count() == 1
        db.session.rollback()
        assert Organization.query.filter_by(slug=slug).count() == 0
