from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

from models import (
    db,
    Organization,
    User,
    RoleEnum,
    Template,
    TemplateItem,
    Job,
    SurveyItem,
    PartRequirement,
    AuditLog,
    JobReportRevisionLog,
    JobStatusEnum,
    MeasurementAuditLog,
    PreSurveyResult,
    DecisionEnum,
    StockStatusEnum,
)
from werkzeug.security import generate_password_hash
from services.job_services import ensure_survey_from_template


@pytest.fixture()
def app_instance(tmp_path, test_app_factory):
    app = test_app_factory(database_uri=f"sqlite:///{tmp_path / 'survey.db'}")
    with app.app_context():
        yield app


@pytest.fixture()
def client(app_instance):
    return app_instance.test_client()


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _completion_state(job_id):
    queries = {
        "job": Job.query.filter_by(id=job_id),
        "survey": SurveyItem.query.filter_by(job_id=job_id),
        "bom": PartRequirement.query.filter_by(job_id=job_id),
        "audit": AuditLog.query.filter_by(job_id=job_id),
        "revisions": JobReportRevisionLog.query.filter_by(job_id=job_id),
        "pre_survey": PreSurveyResult.query.filter_by(job_id=job_id),
        "measurements": MeasurementAuditLog.query.join(SurveyItem).filter(
            SurveyItem.job_id == job_id
        ),
    }
    # Copy every persisted field, including IDs and timestamps, so a repeat
    # cannot silently replace rows or change content while preserving counts.
    return {
        name: [
            {column.key: getattr(row, column.key) for column in row.__table__.columns}
            for row in sorted(query.all(), key=lambda row: row.id)
        ]
        for name, query in queries.items()
    }


def test_survey_complete_idempotent(app_instance, client):
    with app_instance.app_context():
        org = Organization(name="Org", slug="orgx")
        db.session.add(org)
        db.session.flush()
        admin = User(
            username="admin@example.com",
            password_hash=generate_password_hash("Password123!"),
            role=RoleEnum.ADMIN,
            organization_id=org.id,
        )
        db.session.add(admin)
        tpl = Template(name="TPL", engine_type="T", organization_id=org.id)
        db.session.add(tpl)
        db.session.flush()
        db.session.add_all([
            TemplateItem(template_id=tpl.id, organization_id=org.id, section="A", pos=1, part_no="P1", name="Part1", qty=1),
            TemplateItem(template_id=tpl.id, organization_id=org.id, section="A", pos=2, part_no="P2", name="Part2", qty=1),
        ])
        job = Job(
            organization_id=org.id,
            job_pack_id="JP9",
            job_number="JN9",
            template_id=tpl.id,
            status=JobStatusEnum.SURVEY,
            created_by_id=admin.id,
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id
        admin_id = admin.id

        db.session.add(
            PreSurveyResult(
                job_id=job_id,
                data='{"Cleaned": true}',
                completed_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        ensure_survey_from_template(job)
        items = SurveyItem.query.filter_by(job_id=job_id).order_by(SurveyItem.pos).all()
        item_ids = [i.id for i in items]
        assert len(item_ids) == 2
        assert job.pre_survey_result is not None
        assert job.survey_version == 0
        assert job.report_revision == 0

    _login(client, admin_id)

    form = {
        "action": "complete",
        "survey_version": "0",
        "visible_ids": ",".join(str(i) for i in item_ids),
    }
    for item_id in item_ids:
        form[f"decision_{item_id}"] = "replace"

    res = client.post(f"/jobs/{job_id}/survey", data=form)
    assert res.status_code == 302
    assert res.location == f"/jobs/{job_id}/parts"

    with app_instance.app_context():
        job = db.session.get(Job, job_id)
        assert job.status == JobStatusEnum.OFFICE
        assert job.survey_version == 1
        assert job.parts_version == 0
        assert job.report_revision == 2

        items = SurveyItem.query.filter_by(job_id=job_id).order_by(SurveyItem.pos).all()
        assert [(item.id, item.decision) for item in items] == [
            (item_id, DecisionEnum.REPLACE) for item_id in item_ids
        ]
        parts = PartRequirement.query.filter_by(job_id=job_id).order_by(PartRequirement.pos).all()
        assert [
            (part.survey_item_id, part.part_no, part.name, part.qty_required, part.stock_status)
            for part in parts
        ] == [
            (item_ids[0], "P1", "Part1", 1, StockStatusEnum.TO_ORDER),
            (item_ids[1], "P2", "Part2", 1, StockStatusEnum.TO_ORDER),
        ]
        logs = AuditLog.query.filter_by(job_id=job_id).order_by(AuditLog.id).all()
        assert [(log.action, log.user_id) for log in logs] == [
            ("status_change", None),
            ("survey_completed", admin_id),
        ]
        revisions = JobReportRevisionLog.query.filter_by(job_id=job_id).order_by(
            JobReportRevisionLog.revision
        ).all()
        assert [(rev.revision, rev.reason, rev.user_id) for rev in revisions] == [
            (1, "status_change:office", None),
            (2, "survey_completed/bom_generated", admin_id),
        ]
        assert MeasurementAuditLog.query.join(SurveyItem).filter(SurveyItem.job_id == job_id).count() == 0
        completed_state = _completion_state(job_id)

    res = client.post(f"/jobs/{job_id}/survey", data=form)
    assert res.status_code == 302
    assert urlsplit(res.location).path == f"/jobs/{job_id}/survey"

    with app_instance.app_context():
        assert _completion_state(job_id) == completed_state


def test_survey_autosave_round_trip_and_stale_rejection(app_instance, client, monkeypatch):
    with app_instance.app_context():
        org = Organization(name="Autosave", slug="autosave")
        db.session.add(org)
        db.session.flush()
        user = User(username="autosave@example.com", password_hash=generate_password_hash("Password123!"),
                    role=RoleEnum.TECHNICIAN, organization_id=org.id)
        template = Template(name="Autosave", engine_type="T", organization_id=org.id)
        db.session.add_all([user, template])
        db.session.flush()
        db.session.add(TemplateItem(template_id=template.id, organization_id=org.id,
                                    section="A", pos=1, part_no="A1", name="Part", qty=1))
        job = Job(organization_id=org.id, job_pack_id="AUTO-1", job_number="AUTO-1",
                  template_id=template.id, status=JobStatusEnum.SURVEY, created_by_id=user.id)
        db.session.add(job)
        db.session.flush()
        db.session.add(PreSurveyResult(job_id=job.id, data="{}", completed_at=datetime.now(timezone.utc)))
        db.session.commit()
        ensure_survey_from_template(job)
        item = SurveyItem.query.filter_by(job_id=job.id).one()
        job_id, item_id, user_id = job.id, item.id, user.id

    _login(client, user_id)
    url = f"/jobs/{job_id}/survey"
    def send(action, version, notes):
        return client.post(url, data={"action": action, "survey_version": str(version),
                                      "visible_ids": str(item_id), f"decision_{item_id}": "replace",
                                      f"notes_{item_id}": notes})

    first = send("autosave", 0, "first")
    assert first.status_code == 200
    assert first.json["status"] == "ok" and first.json["survey_version"] == 1
    second = send("autosave", first.json["survey_version"], "second")
    assert second.status_code == 200
    assert second.json["survey_version"] == 2
    with app_instance.app_context():
        before_stale = _completion_state(job_id)
    stale = send("autosave", 0, "must not persist")
    assert stale.status_code == 409
    with app_instance.app_context():
        assert _completion_state(job_id) == before_stale
        assert db.session.get(SurveyItem, item_id).notes == "second"
        assert db.session.get(Job, job_id).survey_version == 2

    import survey.routes as survey_routes
    with monkeypatch.context() as patch:
        patch.setattr(survey_routes, "log_event", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("failure after edits")))
        with pytest.raises(RuntimeError, match="failure after edits"):
            send("save", 2, "partial must roll back")
    with app_instance.app_context():
        assert _completion_state(job_id) == before_stale

    manual = send("save", second.json["survey_version"], "manual")
    assert manual.status_code == 302
    with app_instance.app_context():
        assert db.session.get(Job, job_id).survey_version == 3
    assert 'value="3"' in client.get(url).get_data(as_text=True)
    completed = send("complete", 3, "completed")
    assert completed.status_code == 302 and completed.location == f"/jobs/{job_id}/parts"
    with app_instance.app_context():
        assert db.session.get(Job, job_id).survey_version == 4
        assert db.session.get(SurveyItem, item_id).notes == "completed"


def test_survey_rejects_cross_section_row_identity(app_for_tests, seed_users, job_id):
    client = app_for_tests.test_client()
    with app_for_tests.app_context():
        job = db.session.get(Job, job_id)
        db.session.add(PreSurveyResult(job_id=job_id, data="{}", completed_at=datetime.now(timezone.utc)))
        items = SurveyItem.query.filter_by(job_id=job_id).order_by(SurveyItem.id).all()
        if len(items) < 2:
            ensure_survey_from_template(job)
            items = SurveyItem.query.filter_by(job_id=job_id).order_by(SurveyItem.id).all()
        items[0].section = "A"
        items[1].section = "B"
        db.session.commit()
        a_id, b_id = items[0].id, items[1].id
        before = _completion_state(job_id)
    from tests.conftest import login_as
    login_as(client, username="admin@example.com")
    response = client.post(f"/jobs/{job_id}/survey?section=B", data={
        "action": "autosave", "survey_version": "0", "visible_ids": str(a_id),
        f"decision_{b_id}": "replace", f"notes_{b_id}": "must not claim saved",
    })
    assert response.status_code == 400
    with app_for_tests.app_context():
        assert _completion_state(job_id) == before
