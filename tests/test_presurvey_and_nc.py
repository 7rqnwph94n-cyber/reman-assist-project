import json
import pytest

from app import create_app
from models import (
    db,
    Template,
    TemplateItem,
    Job,
    SurveyItem,
    PartRequirement,
    PreSurveyResult,
    User,
    JobStatusEnum,
    RoleEnum,
    Organization,
)


@pytest.fixture
def app_instance():
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.create_all()
        db.session.add(Organization(name="Presurvey Org", slug="presurvey-org"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def seed_template_with_presurvey():
    org = Organization.query.filter_by(slug="presurvey-org").first()
    tpl = Template(
        name="Presurvey Template",
        engine_type="PX",
        organization_id=org.id,
        pre_survey_schema=json.dumps(
            [
                {"label": "Alternator fitted", "type": "checkbox", "options": ""},
                {"label": "Arrival condition", "type": "select", "options": "Clean,Dirty"},
            ]
        ),
    )
    db.session.add(tpl)
    db.session.flush()

    db.session.add(
        TemplateItem(
            template_id=tpl.id,
            organization_id=org.id,
            section="A",
            pos=1,
            part_no="ALT-001",
            name="Alternator",
            qty=1,
            big_ticket=True,
        )
    )
    db.session.commit()
    return tpl


def test_presurvey_render_and_save(app_instance, client):
    with app_instance.app_context():
        tpl = seed_template_with_presurvey()
        org = Organization.query.filter_by(slug="presurvey-org").first()
        user = User(username="admin", password_hash="x", role=RoleEnum.ADMIN, organization_id=org.id)
        db.session.add(user)
        db.session.commit()
        job = Job(
            job_number="PS-001",
            job_pack_id="PS-001",
            status=JobStatusEnum.PRE_SURVEY,
            organization_id=org.id,
            template_id=tpl.id,
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id
        user_id = user.id

    # set logged-in session (auth utils expects session flag); use admin role mimic
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp = client.get(f"/jobs/{job_id}/pre_survey")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Alternator fitted" in html
    assert "Arrival condition" in html
    assert "Clean" in html

    # Submit the form
    resp = client.post(
        f"/jobs/{job_id}/pre_survey",
        data={
            "field_1": "on",  # checkbox
            "field_2": "Dirty",  # select
            "notes": "Oil on casing",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302  # redirect to survey

    with app_instance.app_context():
        ps = PreSurveyResult.query.filter_by(job_id=job_id).first()
        assert ps is not None
        data = json.loads(ps.data)
        assert data.get("Alternator fitted") is True
        assert data.get("Arrival condition") == "Dirty"
        assert ps.notes == "Oil on casing"
