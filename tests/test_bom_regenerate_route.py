import pytest

from models import (
    db,
    Job,
    Template,
    TemplateItem,
    SurveyItem,
    PartRequirement,
    DecisionEnum,
    JobStatusEnum,
    User,
    Organization,
)
from tests.conftest import login_as


def _create_job_with_survey(app_for_tests):
    with app_for_tests.app_context():
        office_user = User.query.filter_by(username="office@example.com").first()
        tech_user = User.query.filter_by(username="tech@example.com").first()
        org = Organization.query.filter_by(slug="global-reman").first()
        template = Template(name="BOM Regen Template", engine_type="BOM", organization_id=org.id)
        db.session.add(template)
        db.session.flush()
        db.session.add_all(
            [
                TemplateItem(
                    template_id=template.id,
                    organization_id=org.id,
                    section="A",
                    pos=1,
                    part_no="RB-001",
                    name="Replace Me",
                    qty=1,
                ),
                TemplateItem(
                    template_id=template.id,
                    organization_id=org.id,
                    section="A",
                    pos=2,
                    part_no="RB-002",
                    name="Reuse Me",
                    qty=1,
                ),
            ]
        )
        job = Job(
            job_number="BOM-REGEN-001",
            job_pack_id="BOM-REGEN-001",
            status=JobStatusEnum.SURVEY,
            template_id=template.id,
            organization_id=org.id,
            assigned_to_id=tech_user.id if tech_user else None,
            created_by_id=office_user.id if office_user else None,
        )
        db.session.add(job)
        db.session.flush()
        replace_item = SurveyItem(
            job_id=job.id,
            section="A",
            pos=1,
            part_no="RB-001",
            name="Replace Me",
            qty=1,
            decision=DecisionEnum.REPLACE,
        )
        reuse_item = SurveyItem(
            job_id=job.id,
            section="A",
            pos=2,
            part_no="RB-002",
            name="Reuse Me",
            qty=1,
            decision=DecisionEnum.REUSE,
        )
        db.session.add_all([replace_item, reuse_item])
        db.session.commit()
        return job.id, replace_item.id


def test_regenerate_bom_creates_lines_for_replace(app_for_tests, client, seed_users):
    job_id, replace_item_id = _create_job_with_survey(app_for_tests)
    login_as(client, username="office@example.com")
    res = client.post(
        f"/jobs/{job_id}/bom/regenerate",
        data={f"amount_required_{replace_item_id}": "2"},
        follow_redirects=False,
    )
    assert res.status_code in {302, 303}
    with app_for_tests.app_context():
        parts = PartRequirement.query.filter_by(job_id=job_id).all()
        assert len(parts) == 1
        assert parts[0].qty_required == 2


@pytest.mark.parametrize("username", ["tech@example.com", "stores@example.com"])
def test_regenerate_bom_forbidden_for_non_office_admin(app_for_tests, client, seed_users, username):
    job_id, _ = _create_job_with_survey(app_for_tests)
    login_as(client, username=username)
    res = client.post(f"/jobs/{job_id}/bom/regenerate", follow_redirects=False)
    assert res.status_code == 403
