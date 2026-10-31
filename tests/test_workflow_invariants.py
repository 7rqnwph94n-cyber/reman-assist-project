import io
import pytest

from flask import url_for

from models import (
    db,
    Job,
    User,
    Template,
    TemplateItem,
    SurveyItem,
    PreSurveyResult,
    JobStatusEnum,
    DecisionEnum,
    MeasurementResultEnum,
    PartRequirement,
    Attachment,
    Organization,
    InvalidJobTransition,
    InvalidCostingTransition,
    StockStatusEnum,
    CostingSheet,
    CostingLine,
    CostingStageEnum,
    MatchStatusEnum,
)
from services.job_services import ensure_survey_from_template
from tests.conftest import login_as


def _create_job_with_measurement(assigned_to_id=None, created_by_id=None):
    org = Organization.query.filter_by(slug="global-reman").first()
    template = Template(name="WF Template", engine_type="WF", organization_id=org.id)
    db.session.add(template)
    db.session.flush()
    db.session.add(
        TemplateItem(
            template_id=template.id,
            organization_id=org.id,
            section="A",
            pos=1,
            part_no="WF-001",
            name="Measured part",
            qty=1,
            requires_measurement=True,
            measurement_min=10.0,
            measurement_max=20.0,
            measurement_unit="mm",
        )
    )
    job = Job(
        job_number="WF-001",
        job_pack_id="WF-001",
        status=JobStatusEnum.SURVEY,
        organization_id=org.id,
        template_id=template.id,
        assigned_to_id=assigned_to_id,
        created_by_id=created_by_id,
    )
    db.session.add(job)
    db.session.commit()
    ensure_survey_from_template(job)
    db.session.add(
        PreSurveyResult(
            job_id=job.id,
            data='{"Cleaned": true}',
        )
    )
    db.session.commit()
    return job


def test_survey_completion_requires_decisions_and_measurements(app_for_tests, client, seed_users):
    with app_for_tests.app_context():
        tech_user = User.query.filter_by(username="tech@example.com").first()
        job = _create_job_with_measurement(assigned_to_id=tech_user.id if tech_user else None)
        item = SurveyItem.query.filter_by(job_id=job.id).first()

    login_as(client, username="tech@example.com")
    with app_for_tests.test_request_context():
        url = url_for("survey.job_survey", job_id=job.id)

    with client.session_transaction() as sess:
        sess[f"pre_survey_done_{job.id}"] = True

    # Attempt completion without decisions/measurements
    res = client.post(
        url,
        data={
            "action": "complete",
            "survey_version": job.survey_version or 0,
            "visible_ids": str(item.id),
        },
        follow_redirects=False,
    )
    assert res.status_code in {302, 303}
    with app_for_tests.app_context():
        job_db = db.session.get(Job, job.id)
        assert job_db.status == JobStatusEnum.SURVEY
        current_version = job_db.survey_version or 0

    # Provide decision + measurement and complete
    res = client.post(
        url,
        data={
            "action": "complete",
            "survey_version": current_version,
            "visible_ids": str(item.id),
            f"decision_{item.id}": DecisionEnum.REPLACE.value,
            f"measurement_value_{item.id}": "15",
            f"spec_min_{item.id}": "10",
            f"spec_max_{item.id}": "20",
            f"measurement_unit_{item.id}": "mm",
        },
        follow_redirects=False,
    )
    assert res.status_code in {302, 303}
    with app_for_tests.app_context():
        job_db = db.session.get(Job, job.id)
        assert job_db.status == JobStatusEnum.OFFICE
        item_db = db.session.get(SurveyItem, item.id)
        assert item_db.measurement_result == MeasurementResultEnum.WITHIN_SPEC


def test_attachment_upload_links_to_job(app_for_tests, client, seed_users, job_id):
    login_as(client, username="office@example.com")
    with app_for_tests.test_request_context():
        url = url_for("jobs.job_attachments", job_id=job_id)

    data = {
        "file": (io.BytesIO(b"hello"), "note.txt"),
    }
    res = client.post(url, data=data, content_type="multipart/form-data", follow_redirects=True)
    assert res.status_code == 200
    with app_for_tests.app_context():
        att = Attachment.query.filter_by(job_id=job_id).first()
        assert att is not None
        assert att.original_filename == "note.txt"


def test_db_integrity_no_orphan_parts(app_for_tests, seed_basic):
    with app_for_tests.app_context():
        parts = PartRequirement.query.all()
        for part in parts:
            job = db.session.get(Job, part.job_id)
            assert job is not None


# ---------------------------------------------------------------------------
# Lifecycle enforcement tests
# ---------------------------------------------------------------------------

def _make_job_at_stage(org, status, *, with_measurement=False, with_costing=False):
    """Helper to create a job at a given status for lifecycle tests."""
    template = Template(name="LC Template", engine_type="LC", organization_id=org.id)
    db.session.add(template)
    db.session.flush()
    if with_measurement:
        db.session.add(TemplateItem(
            template_id=template.id, organization_id=org.id,
            section="A", pos=1, part_no="LC-001", name="Measured part", qty=1,
            requires_measurement=True, measurement_min=10.0, measurement_max=20.0, measurement_unit="mm",
        ))
    else:
        db.session.add(TemplateItem(
            template_id=template.id, organization_id=org.id,
            section="A", pos=1, part_no="LC-001", name="Simple part", qty=1,
        ))
    job = Job(
        job_number=f"LC-{id(template)}",
        job_pack_id=f"LC-{id(template)}",
        status=status,
        organization_id=org.id,
        template_id=template.id,
    )
    db.session.add(job)
    db.session.commit()
    ensure_survey_from_template(job)
    db.session.commit()

    if with_costing:
        sheet = CostingSheet(job_id=job.id)
        db.session.add(sheet)
        db.session.flush()
        line = CostingLine(costing_sheet_id=sheet.id, line_no=1, oem_part_no="LC-001", part_description="part")
        db.session.add(line)
        db.session.commit()

    return job


def test_complete_blocked_by_unmeasured_items(app_for_tests, seed_users):
    """COMPLETE should be blocked when required measurements are missing."""
    with app_for_tests.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job = _make_job_at_stage(org, JobStatusEnum.BUILD, with_measurement=True)
        # Survey item should have requires_measurement=True and NOT_MEASURED
        si = SurveyItem.query.filter_by(job_id=job.id).first()
        assert si.requires_measurement is True
        assert si.measurement_result == MeasurementResultEnum.NOT_MEASURED
        with pytest.raises(InvalidJobTransition, match="measurement"):
            job.transition_to(JobStatusEnum.COMPLETE)


def test_complete_allowed_when_measurements_done(app_for_tests, seed_users):
    """COMPLETE should succeed when all measurements are recorded."""
    with app_for_tests.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job = _make_job_at_stage(org, JobStatusEnum.BUILD, with_measurement=True)
        si = SurveyItem.query.filter_by(job_id=job.id).first()
        si.measurement_result = MeasurementResultEnum.WITHIN_SPEC
        si.measurement_value = "15.0"
        si.decision = DecisionEnum.REUSE
        db.session.commit()
        job.transition_to(JobStatusEnum.COMPLETE)
        assert job.status == JobStatusEnum.COMPLETE


def test_build_blocked_by_empty_costing_sheet(app_for_tests, seed_users):
    """BUILD should be blocked when a costing sheet exists but has no matched lines."""
    with app_for_tests.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job = _make_job_at_stage(org, JobStatusEnum.OFFICE, with_costing=True)
        # Line should default to UNMATCHED
        sheet = CostingSheet.query.filter_by(job_id=job.id).first()
        assert sheet is not None
        assert all(l.match_status != MatchStatusEnum.MATCHED for l in sheet.lines)
        with pytest.raises(InvalidJobTransition, match="costing"):
            job.transition_to(JobStatusEnum.BUILD)


def test_build_allowed_without_costing_sheet(app_for_tests, seed_users):
    """BUILD should succeed when no costing sheet exists."""
    with app_for_tests.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job = _make_job_at_stage(org, JobStatusEnum.OFFICE)
        job.transition_to(JobStatusEnum.BUILD)
        assert job.status == JobStatusEnum.BUILD


def test_costing_stage_valid_transitions(app_for_tests, seed_users):
    """Valid costing stage transitions should succeed."""
    with app_for_tests.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job = _make_job_at_stage(org, JobStatusEnum.OFFICE, with_costing=True)
        sheet = CostingSheet.query.filter_by(job_id=job.id).first()
        assert sheet.stage == CostingStageEnum.AWAITING_SAS
        sheet.transition_stage_to(CostingStageEnum.COSTING_IN_PROGRESS)
        assert sheet.stage == CostingStageEnum.COSTING_IN_PROGRESS
        sheet.transition_stage_to(CostingStageEnum.AWAITING_PO)
        assert sheet.stage == CostingStageEnum.AWAITING_PO
        sheet.transition_stage_to(CostingStageEnum.ENGINE_IN_BUILD)
        assert sheet.stage == CostingStageEnum.ENGINE_IN_BUILD
        sheet.transition_stage_to(CostingStageEnum.COMPLETE)
        assert sheet.stage == CostingStageEnum.COMPLETE


def test_costing_stage_invalid_transition(app_for_tests, seed_users):
    """Invalid costing stage transitions should raise InvalidCostingTransition."""
    with app_for_tests.app_context():
        org = Organization.query.filter_by(slug="global-reman").first()
        job = _make_job_at_stage(org, JobStatusEnum.OFFICE, with_costing=True)
        sheet = CostingSheet.query.filter_by(job_id=job.id).first()
        assert sheet.stage == CostingStageEnum.AWAITING_SAS
        with pytest.raises(InvalidCostingTransition):
            sheet.transition_stage_to(CostingStageEnum.COMPLETE)
