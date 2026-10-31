import pytest

from app import create_app
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
)
from werkzeug.security import generate_password_hash
from services.job_services import ensure_survey_from_template


@pytest.fixture()
def app_instance(tmp_path):
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'survey.db'}",
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        ENFORCE_CSRF=False,
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app_instance):
    return app_instance.test_client()


def _login(client, user_id, job_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess[f"pre_survey_done_{job_id}"] = True


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

        ensure_survey_from_template(job)
        items = SurveyItem.query.filter_by(job_id=job_id).all()
        item_ids = [i.id for i in items]

    _login(client, admin_id, job_id)

    form = {
        "action": "complete",
        "survey_version": "0",
        "visible_ids": ",".join(str(i) for i in item_ids),
    }
    for item_id in item_ids:
        form[f"decision_{item_id}"] = "replace"

    res = client.post(f"/jobs/{job_id}/survey", data=form)
    assert res.status_code == 302

    with app_instance.app_context():
        bom_count = PartRequirement.query.filter_by(job_id=job_id).count()
        log_count = AuditLog.query.filter_by(job_id=job_id, action="survey_completed").count()
        rev_count = JobReportRevisionLog.query.filter_by(job_id=job_id).count()
        meas_count = MeasurementAuditLog.query.join(SurveyItem).filter(SurveyItem.job_id == job_id).count()
        job_status = db.session.get(Job, job_id).status
        assert bom_count == len(item_ids)
        assert log_count == 1
        assert job_status == JobStatusEnum.OFFICE
        assert meas_count == 0

    res = client.post(f"/jobs/{job_id}/survey", data=form)
    assert res.status_code == 302

    with app_instance.app_context():
        bom_count2 = PartRequirement.query.filter_by(job_id=job_id).count()
        log_count2 = AuditLog.query.filter_by(job_id=job_id, action="survey_completed").count()
        rev_count2 = JobReportRevisionLog.query.filter_by(job_id=job_id).count()
        meas_count2 = MeasurementAuditLog.query.join(SurveyItem).filter(SurveyItem.job_id == job_id).count()
        job_status2 = db.session.get(Job, job_id).status
        assert bom_count2 == bom_count
        assert log_count2 == log_count
        assert rev_count2 == rev_count
        assert job_status2 == job_status
        assert meas_count2 == meas_count
