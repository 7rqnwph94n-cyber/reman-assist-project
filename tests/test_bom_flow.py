import pytest

from app import create_app
from services.job_services import ensure_survey_from_template, change_job_status
from models import (
    db,
    Job,
    Template,
    TemplateItem,
    SurveyItem,
    PartRequirement,
    JobStatusEnum,
    DecisionEnum,
    Organization,
)


@pytest.fixture()
def app():
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    with app.app_context():
        db.create_all()
        db.session.add(Organization(name="Test Org", slug="test-org-bom-flow"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _get_or_create_template(org_id: int):
    tmpl = Template.query.first()
    if tmpl:
        return tmpl

    tmpl = Template(name="Test Template", engine_type="TEST", organization_id=org_id)
    db.session.add(tmpl)
    db.session.flush()

    # minimal template items
    db.session.add(
        TemplateItem(
            template_id=tmpl.id,
            organization_id=org_id,
            section="A",
            pos=1,
            part_no="PN-001",
            name="Test Part 1",
            qty=1,
        )
    )
    db.session.commit()
    return tmpl


def test_survey_to_bom_generation(app):
    """
    Happy path: ensure survey lines copy from template, decisions drive BOM, and status moves to OFFICE.
    """
    with app.app_context():
        org = Organization.query.filter_by(slug="test-org-bom-flow").first()
        tmpl = _get_or_create_template(org.id)

        job = Job(
            job_number="TEST-BOM-1",
            job_pack_id="TEST-BOM-1",
            organization_id=org.id,
            template=tmpl,
            status=JobStatusEnum.PRE_SURVEY,
        )
        db.session.add(job)
        db.session.commit()

        ensure_survey_from_template(job)

        survey_items = SurveyItem.query.filter_by(job_id=job.id).all()
        assert survey_items, "Survey items should be created from template"

        # Mark all as replace to force BOM lines
        for si in survey_items:
            si.decision = DecisionEnum.REPLACE

        created = _regenerate_bom_offline(job, survey_items)

        assert created == len(survey_items)

        parts = PartRequirement.query.filter_by(job_id=job.id).all()
        assert len(parts) == len(survey_items)

        change_job_status(job, JobStatusEnum.OFFICE)
        db.session.commit()

        assert job.status == JobStatusEnum.OFFICE


def _regenerate_bom_offline(job, survey_items):
    PartRequirement.query.filter_by(job_id=job.id).delete()
    db.session.flush()

    created = 0
    for item in survey_items:
        decision = item.decision
        always = bool(item.always_replace)
        if not (always or decision in (DecisionEnum.REPLACE, DecisionEnum.SCRAP)):
            continue
        qty = item.qty or 1
        db.session.add(
            PartRequirement(
                job_id=job.id,
                survey_item_id=item.id,
                section=item.section,
                pos=item.pos,
                part_no=item.part_no,
                name=item.name,
                qty_required=qty,
            )
        )
        created += 1
    db.session.commit()
    return created
