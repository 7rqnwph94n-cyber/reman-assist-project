"""Real PostgreSQL workflow regressions; run only through the dedicated gate."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from urllib.parse import urlsplit
from uuid import uuid4
from sqlalchemy import event

import pytest
from werkzeug.security import generate_password_hash

from models import (
    db, Organization, User, RoleEnum, Template, TemplateItem, Job, JobStatusEnum,
    SurveyItem, PreSurveyResult, PartRequirement, StockStatusEnum, DecisionEnum,
    AuditLog, JobReportRevisionLog, MeasurementAuditLog, InvalidJobTransition, Attachment, JobLog,
)
from services.job_services import change_job_status
from utils.tenant_scope import set_current_org_id


PASSWORD = "PostgresTestOnly123!"


def test_overlapping_survey_saves_claim_one_version(postgres_app, client, job_data):
    """Synchronise both requests at the database version write, not at test start."""
    job_id = job_data["job_id"]
    tech = job_data["users"]["owner"][RoleEnum.TECHNICIAN]
    login(client, tech)
    response = client.post(f"/jobs/{job_id}/pre_survey", data={"field_1": "on"})
    assert response.status_code == 302
    with postgres_app.app_context():
        item_id = SurveyItem.query.filter_by(job_id=job_id).first().id
        before_audit = [(row.id, row.action) for row in AuditLog.query.filter_by(job_id=job_id).order_by(AuditLog.id)]
        engine = db.engine

    clients = [postgres_app.test_client(), postgres_app.test_client()]
    for caller in clients:
        login(caller, tech)
    read_barrier = Barrier(2, timeout=10)
    barrier = Barrier(2, timeout=10)
    seen = local()

    def after_read(conn, cursor, statement, parameters, context, executemany):
        if not getattr(seen, "job_read", False) and statement.lstrip().upper().startswith("SELECT") and "FROM jobs" in statement:
            seen.job_read = True
            read_barrier.wait()

    def before_write(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE JOBS SET") and "survey_version" in statement:
            barrier.wait()

    def save(index):
        return clients[index].post(f"/jobs/{job_id}/survey", data={
            "action": "autosave", "survey_version": "0", "visible_ids": str(item_id),
            f"decision_{item_id}": "replace", f"notes_{item_id}": f"writer {index}",
        })

    event.listen(engine, "after_cursor_execute", after_read)
    event.listen(engine, "before_cursor_execute", before_write)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, index) for index in range(2)]
            results = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(engine, "after_cursor_execute", after_read)
        event.remove(engine, "before_cursor_execute", before_write)

    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(index for index, response in enumerate(results) if response.status_code == 200)
    assert results[winner].json["survey_version"] == 1
    with postgres_app.app_context():
        assert db.session.get(Job, job_id).survey_version == 1
        assert db.session.get(SurveyItem, item_id).notes == f"writer {winner}"
        assert [(row.id, row.action) for row in AuditLog.query.filter_by(job_id=job_id).order_by(AuditLog.id)] == before_audit


def login(client, user):
    # The fixture may already be logged into another tenant. Follow the public
    # logout flow rather than querying credentials under that tenant's scope.
    with client.session_transaction() as session:
        authenticated = "user_id" in session
    if authenticated:
        response = client.get("/logout")
        assert response.status_code == 302 and urlsplit(response.location).path == "/login"
        with client.session_transaction() as session:
            assert "user_id" not in session
    response = client.post("/login", data={"username": user["username"], "password": PASSWORD})
    with client.session_transaction() as session:
        assert response.status_code == 302, (response.status_code, session.get("_flashes", []))
        assert session["user_id"] == user["id"]
    expected = "/stores" if user["role"] == RoleEnum.STORES else "/dashboard"
    assert urlsplit(response.location).path == expected
    with client.application.app_context():
        persisted = db.session.get(User, user["id"])
        assert persisted.username == user["username"] and persisted.role == user["role"]
        assert persisted.organization_id == user["org_id"]
        audit = AuditLog.query.filter_by(action="login", user_id=user["id"]).order_by(AuditLog.id.desc()).first()
        assert audit is not None and audit.message == f"User logged in: {user['username']}"


def state(job_id):
    queries = {
        "job": Job.query.filter_by(id=job_id),
        "survey": SurveyItem.query.filter_by(job_id=job_id),
        "pre_survey": PreSurveyResult.query.filter_by(job_id=job_id),
        "bom": PartRequirement.query.filter_by(job_id=job_id),
        "audit": AuditLog.query.filter_by(job_id=job_id),
        "revisions": JobReportRevisionLog.query.filter_by(job_id=job_id),
        "measurements": MeasurementAuditLog.query.join(SurveyItem).filter(SurveyItem.job_id == job_id),
        "attachments": Attachment.query.filter_by(job_id=job_id),
        "job_logs": JobLog.query.filter_by(job_id=job_id),
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
                users[label][role] = {"id": user.id, "username": user.username, "org_id": org.id, "role": role}
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
        other = users["other"]
        own_job = Job(
            job_number=f"PG-own-{token}", job_pack_id=f"PG-own-{token}",
            organization_id=other[RoleEnum.ADMIN]["org_id"],
            assigned_to_id=other[RoleEnum.TECHNICIAN]["id"], created_by_id=other[RoleEnum.OFFICE]["id"],
        )
        db.session.add(own_job)
        db.session.commit()
        other_job_id = own_job.id
    return {"job_id": job_id, "template_id": template_id, "users": users, "other_job_id": other_job_id}


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
    assert_cross_organisation_isolation(postgres_app, client, job_data, role)


def assert_cross_organisation_isolation(app, client, job_data, role):
    """Shared HTTP contract; local SQLite regressions are explicitly separate."""
    job_id = job_data["job_id"]
    outsider = job_data["users"]["other"][role]
    login(client, outsider)
    own_job_id = job_data["other_job_id"]
    with app.app_context():
        before = state(job_id)
        assert len(before["job"]) == 1 and before["survey"]
        own_before = state(own_job_id)
        assert own_before["job"][0]["organization_id"] == outsider["org_id"]
        set_current_org_id(outsider["org_id"])
        try:
            assert db.session.get(Job, job_id) is None
            assert db.session.get(Template, job_data["template_id"]) is None
            assert db.session.get(Job, own_job_id) is not None
        finally:
            set_current_org_id(None)
    # All three users can read their own job, not just receive a login redirect.
    response = client.get(f"/jobs/{own_job_id}")
    assert response.status_code == 200
    assert own_before["job"][0]["job_number"] in response.get_data(as_text=True)
    requests = [
        ("GET", f"/jobs/{job_id}", {}, 404),
        ("GET", f"/jobs/{job_id}/survey", {}, 404),
        ("POST", f"/jobs/{job_id}/survey", {"action": "complete", "survey_version": "0"}, 404),
        ("GET", f"/jobs/{job_id}/parts", {}, 403 if role == RoleEnum.TECHNICIAN else 404),
        ("POST", f"/jobs/{job_id}/parts", {"action": "save"}, 403 if role == RoleEnum.TECHNICIAN else 404),
        ("POST", f"/jobs/{job_id}/pre_survey", {"field_1": "on", "notes": "denied write"},
         403 if role == RoleEnum.OFFICE else 404),
        ("POST", f"/admin/jobs/{job_id}/status", {"status": "complete", "reason": "denied override"},
         404 if role == RoleEnum.ADMIN else 403),
    ]
    for method, path, form, expected in requests:
        response = client.open(path, method=method, data=form)
        # Role decorators may reject before lookup; supported roles get the
        # tenant-scoped 404. Neither outcome may redirect to authentication.
        assert response.status_code == expected, (role, method, path, response.status_code)
        with client.session_transaction() as session:
            assert session["user_id"] == outsider["id"]
        with app.app_context():
            assert state(job_id) == before
            assert state(own_job_id) == own_before
    # Authorised writes still work for Admin/Technician; Office remains denied.
    response = client.post(f"/jobs/{own_job_id}/pre_survey", data={"notes": "own tenant write"})
    assert response.status_code == (403 if role == RoleEnum.OFFICE else 302)
    with app.app_context():
        if role == RoleEnum.OFFICE:
            assert state(own_job_id) == own_before
        else:
            assert urlsplit(response.location).path == f"/jobs/{own_job_id}/survey"
            assert PreSurveyResult.query.filter_by(job_id=own_job_id).one().notes == "own tenant write"
        assert state(job_id) == before


def test_postgres_transaction_rollback(postgres_app):
    slug = f"rollback-{uuid4().hex}"
    with postgres_app.app_context():
        db.session.add(Organization(name=slug, slug=slug))
        db.session.flush()
        assert Organization.query.filter_by(slug=slug).count() == 1
        db.session.rollback()
        assert Organization.query.filter_by(slug=slug).count() == 0
