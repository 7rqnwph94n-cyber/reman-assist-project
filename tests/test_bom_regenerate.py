from models import (
    db,
    Job,
    Template,
    TemplateItem,
    SurveyItem,
    PartRequirement,
    DecisionEnum,
    JobStatusEnum,
    Organization,
)
from services.bom import regenerate_bom_for_job
from services.bom_services import apply_supersedes


def _create_job(template_name: str, job_number: str):
    org = Organization.query.filter_by(slug="global-reman").first()
    template = Template(name=template_name, engine_type="Test", organization_id=org.id)
    db.session.add(template)
    db.session.flush()
    job = Job(
        job_number=job_number,
        job_pack_id=job_number,
        status=JobStatusEnum.SURVEY,
        template_id=template.id,
        organization_id=org.id,
    )
    db.session.add(job)
    db.session.commit()
    return job, template


def test_regenerate_bom_from_decisions(app_for_tests):
    with app_for_tests.app_context():
        job, _template = _create_job("BOM Template", "BOM-001")
        item_replace = SurveyItem(
            job_id=job.id,
            part_no="P-REPL",
            name="Replace Part",
            qty=2,
            decision=DecisionEnum.REPLACE,
        )
        item_scrap = SurveyItem(
            job_id=job.id,
            part_no="P-SCRAP",
            name="Scrap Part",
            qty=4,
            decision=DecisionEnum.SCRAP,
        )
        item_reuse = SurveyItem(
            job_id=job.id,
            part_no="P-REUSE",
            name="Reuse Part",
            qty=5,
            decision=DecisionEnum.REUSE,
        )
        item_always = SurveyItem(
            job_id=job.id,
            part_no="P-ALWAYS",
            name="Always Replace",
            qty=3,
            decision=DecisionEnum.REUSE,
            always_replace=True,
        )
        db.session.add_all([item_replace, item_scrap, item_reuse, item_always])
        db.session.commit()

        survey_items = SurveyItem.query.filter_by(job_id=job.id).all()
        form_data = {f"amount_required_{item_replace.id}": "7"}
        created = regenerate_bom_for_job(job, survey_items, form_data)
        db.session.commit()

        assert created == 3
        parts = PartRequirement.query.filter_by(job_id=job.id).all()
        part_nos = {p.part_no for p in parts}
        assert "P-REPL" in part_nos
        assert "P-SCRAP" in part_nos
        assert "P-ALWAYS" in part_nos
        assert "P-REUSE" not in part_nos

        repl = PartRequirement.query.filter_by(job_id=job.id, part_no="P-REPL").first()
        scrap = PartRequirement.query.filter_by(job_id=job.id, part_no="P-SCRAP").first()
        assert repl is not None
        assert repl.qty_required == 7
        assert scrap is not None
        assert scrap.qty_required == 4


def test_supersedes_removes_target_lines(app_for_tests):
    with app_for_tests.app_context():
        job, template = _create_job("Supersede Template", "BOM-002")
        kit_item = TemplateItem(
            template_id=template.id,
            organization_id=job.organization_id,
            part_no="KIT-001",
            name="Kit Master",
            supersedes="PART-002",
        )
        target_item = TemplateItem(
            template_id=template.id,
            organization_id=job.organization_id,
            part_no="PART-002",
            name="Target Part",
        )
        db.session.add_all([kit_item, target_item])
        db.session.flush()

        db.session.add_all(
            [
                SurveyItem(
                    job_id=job.id,
                    part_no="KIT-001",
                    name="Kit Master",
                    qty=1,
                    decision=DecisionEnum.REPLACE,
                ),
                SurveyItem(
                    job_id=job.id,
                    part_no="PART-002",
                    name="Target Part",
                    qty=2,
                    decision=DecisionEnum.REPLACE,
                ),
            ]
        )
        db.session.commit()

        survey_items = SurveyItem.query.filter_by(job_id=job.id).all()
        regenerate_bom_for_job(job, survey_items, {})
        apply_supersedes(job.id)
        db.session.commit()

        parts = PartRequirement.query.filter_by(job_id=job.id).all()
        part_nos = {p.part_no for p in parts}
        assert part_nos == {"KIT-001"}
