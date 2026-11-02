"""Server-rendered save targets for large, filtered surveys."""

from datetime import datetime, timezone
from html import unescape
import re

from models import db, Job, PreSurveyResult, SurveyItem, TemplateItem
from services.job_services import ensure_survey_from_template
from tests.conftest import login_as


def _survey_form(html):
    form = re.search(r'<form\b[^>]*class="survey-form[^>]*>', html)
    assert form is not None
    target = re.search(r'\baction="([^"]+)"', form.group())
    visible = re.search(r'<input type="hidden" name="visible_ids" value="([^"]+)"', html)
    version = re.search(r'<input type="hidden" name="survey_version" value="([^"]+)"', html)
    assert target and visible and version
    return unescape(target.group(1)), visible.group(1), version.group(1)


def test_large_survey_form_targets_preserve_page_and_section(app_for_tests, seed_users, job_id):
    with app_for_tests.app_context():
        job = db.session.get(Job, job_id)
        template_id, org_id = job.template_id, job.organization_id
        db.session.add_all([
            TemplateItem(template_id=template_id, organization_id=org_id,
                         section=("TA" if index % 5 == 0 else "OTHER"),
                         pos=index, part_no=f"PAGE-{index}", name=f"Page part {index}", qty=1)
            for index in range(1, 501)
        ])
        db.session.add(PreSurveyResult(job_id=job_id, data="{}", completed_at=datetime.now(timezone.utc)))
        db.session.commit()
        ensure_survey_from_template(job)
        assert SurveyItem.query.filter_by(job_id=job_id).count() >= 500

    client = app_for_tests.test_client()
    login_as(client, username="admin@example.com")
    bare = _survey_form(client.get(f"/jobs/{job_id}/survey").get_data(as_text=True))
    equivalent = _survey_form(client.get(
        f"/jobs/{job_id}/survey?page=1&per_page=100&section=all"
    ).get_data(as_text=True))
    assert bare == equivalent
    for query, note in (("?page=2&per_page=100", "page two"),
                        ("?section=TA&page=1&per_page=100", "filtered")):
        response = client.get(f"/jobs/{job_id}/survey{query}")
        assert response.status_code == 200
        action, visible_ids, version = _survey_form(response.get_data(as_text=True))
        assert "per_page=100" in action
        if "section=TA" in query:
            assert "section=TA" in action
        else:
            assert "page=2" in action
        item_id = int(visible_ids.split(",")[0])
        if "page=2" in query:
            # This is the old background-save target: it resolves page 1.
            wrong_target = client.post(f"/jobs/{job_id}/survey", data={
                "action": "autosave", "survey_version": version,
                "visible_ids": visible_ids, f"notes_{item_id}": "must not persist"})
            assert wrong_target.status_code == 400
            with app_for_tests.app_context():
                assert db.session.get(SurveyItem, item_id).notes is None
        saved = client.post(action, data={"action": "autosave", "survey_version": version,
                                          "visible_ids": visible_ids, f"notes_{item_id}": note})
        assert saved.status_code == 200 and saved.json["status"] == "ok"
        with app_for_tests.app_context():
            assert db.session.get(SurveyItem, item_id).notes == note
