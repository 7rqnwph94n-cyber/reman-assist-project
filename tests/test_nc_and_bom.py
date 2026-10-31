"""
BOM behavior tests:
- REUSE parts are pruned from BOM.
"""

import pytest
from app import create_app
from models import (
    db,
    Job,
    Template,
    TemplateItem,
    SurveyItem,
    PartRequirement,
    DecisionEnum,
    StockStatusEnum,
    JobStatusEnum,
    Organization,
)
from services.bom_services import prune_good_parts
from services.job_services import ensure_survey_from_template


@pytest.fixture
def app_instance():
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        TESTING=True,
    )
    with app.app_context():
        db.create_all()
        db.session.add(Organization(name="NC Org", slug="nc-org"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def seed_job_with_template():
    org = Organization.query.filter_by(slug="nc-org").first()
    tpl = Template(name="NC Test", engine_type="T", organization_id=org.id)
    db.session.add(tpl)
    db.session.flush()
    items = [
        TemplateItem(
            template_id=tpl.id,
            organization_id=org.id,
            section="A",
            pos=1,
            part_no="BT",
            name="Big Ticket",
            qty=1,
            big_ticket=True,
        ),
        TemplateItem(
            template_id=tpl.id,
            organization_id=org.id,
            section="B",
            pos=1,
            part_no="GOOD",
            name="Reusable",
            qty=1,
            big_ticket=False,
        ),
    ]
    db.session.add_all(items)
    db.session.commit()
    job = Job(
        job_number="NC-001",
        job_pack_id="NC-001",
        status=JobStatusEnum.SURVEY,
        organization_id=org.id,
        template_id=tpl.id,
    )
    db.session.add(job)
    db.session.commit()
    return job


def test_prune_good_parts(app_instance):
    with app_instance.app_context():
        job = seed_job_with_template()
        ensure_survey_from_template(job)
        survey_items = SurveyItem.query.filter_by(job_id=job.id).all()

        # Mark decisions: big-ticket REPLACE, other REUSE
        for si in survey_items:
            if si.big_ticket:
                si.decision = DecisionEnum.REPLACE
            else:
                si.decision = DecisionEnum.REUSE
        db.session.commit()

        # Create BOM lines for both
        for si in survey_items:
            pr = PartRequirement(
                job_id=job.id,
                survey_item_id=si.id,
                section=si.section,
                pos=si.pos,
                part_no=si.part_no,
                name=si.name,
                qty_required=si.qty or 1,
                stock_status=StockStatusEnum.TO_ORDER,
            )
            db.session.add(pr)
        db.session.commit()

        # Prune good parts (REUSE)
        prune_good_parts(job.id)
        remaining = PartRequirement.query.filter_by(job_id=job.id).all()
        assert len(remaining) == 1
        assert remaining[0].part_no == "BT"
