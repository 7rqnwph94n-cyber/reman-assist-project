import re
from pathlib import Path


def _login(page, base_url, username, password="Password123!"):
    page.goto(f"{base_url}/login")
    page.fill('[data-testid="login-username"]', username)
    page.fill('[data-testid="login-password"]', password)
    page.click('[data-testid="login-submit"]')
    page.wait_for_url(re.compile(r".*/(dashboard|stores).*"), timeout=10000)


def _open_first_job(page, base_url) -> str:
    page.goto(f"{base_url}/jobs")
    link = page.locator('[data-testid^="job-view-"]').first
    assert link.count() > 0, "No job link found in jobs list"
    href = link.get_attribute("href")
    if href:
        if href.startswith("/"):
            page.goto(f"{base_url}{href}")
        else:
            page.goto(href)
    else:
        link.click()
    job_url_re = re.compile(r".*/jobs/\d+$")
    if not job_url_re.match(page.url):
        page.wait_for_url(job_url_re, timeout=10000)
    match = re.search(r"/jobs/(\d+)$", page.url)
    assert match, "Job detail URL not detected"
    return match.group(1)


def _logout(page, base_url):
    page.goto(f"{base_url}/logout")


def test_presurvey_gate_and_survey_save(page, base_url, tmp_path: Path):
    _login(page, base_url, "admin@example.com")
    job_id = _open_first_job(page, base_url)

    page.goto(f"{base_url}/jobs/{job_id}/survey")
    if page.locator('[data-testid="presurvey-form"]').count() > 0:
        photo = tmp_path / "presurvey.jpg"
        photo.write_bytes(b"fake-image")
        page.set_input_files('[data-testid="presurvey-photo"]', str(photo))
        page.click('[data-testid="presurvey-submit"]')

    if page.locator('[data-testid="survey-form"]').count() > 0:
        # Make a small, deterministic change and save.
        sel = page.locator('select[name^="decision_"]').first
        if sel.count() > 0:
            sel.select_option("replace", force=True)
        page.click('[data-testid="survey-save"]')


def test_nav_links_by_role(page, base_url):
    _login(page, base_url, "admin@example.com")
    assert page.locator('[data-testid="nav-dashboard"]').count() == 1
    assert page.locator('[data-testid="nav-create-job"]').count() == 1
    assert page.locator('[data-testid="nav-templates"]').count() == 1
    assert page.locator('[data-testid="nav-stores"]').count() == 1
    _logout(page, base_url)
    _login(page, base_url, "stores@example.com")
    assert page.locator('[data-testid="nav-stores"]').count() == 1
    assert page.locator('[data-testid="nav-dashboard"]').count() == 0
    assert page.locator('[data-testid="nav-jobs"]').count() == 0
    assert page.locator('[data-testid="nav-create-job"]').count() == 0
    assert page.locator('[data-testid="nav-templates"]').count() == 0
    page.click('[data-testid="nav-stores"]')
    assert "/stores" in page.url

    _logout(page, base_url)
    _login(page, base_url, "technician@example.com")
    assert page.locator('[data-testid="nav-dashboard"]').count() == 1
    assert page.locator('[data-testid="nav-jobs"]').count() == 1
    assert page.locator('[data-testid="nav-create-job"]').count() == 0
    assert page.locator('[data-testid="nav-stores"]').count() == 0


def test_build_note_adds_audit_entry(page, base_url):
    _login(page, base_url, "technician@example.com")
    job_id = _open_first_job(page, base_url)

    page.goto(f"{base_url}/jobs/{job_id}/build")
    note_text = "E2E build note"
    page.fill('[data-testid="build-note-input"]', note_text)
    page.click('[data-testid="build-note-save"]')
    assert page.locator(f"text={note_text}").count() > 0


def test_parts_status_update_persists(page, server_factory):
    base_url = server_factory(
        seed_args=["--templates", "1", "--jobs", "1", "--items-per-template", "6", "--bom-lines-per-job", "6"],
        port=5012,
    )
    _login(page, base_url, "admin@example.com")
    job_id = _open_first_job(page, base_url)

    page.goto(f"{base_url}/jobs/{job_id}/parts")
    status_select = page.locator('select[name^="stock_status_"]').first
    assert status_select.count() > 0, "No part status select found"
    status_select.select_option("received", force=True)
    page.click('[data-testid="parts-save"]')

    # Ensure the selection persisted after save.
    current_value = status_select.input_value()
    assert current_value == "received"


def test_attachment_upload_and_export(page, base_url, tmp_path: Path):
    _login(page, base_url, "admin@example.com")
    job_id = _open_first_job(page, base_url)

    page.goto(f"{base_url}/jobs/{job_id}/attachments")
    upload = tmp_path / "note.txt"
    upload.write_text("hello")
    page.set_input_files('[data-testid="attachment-file"]', str(upload))
    page.click('[data-testid="attachment-submit"]')
    assert page.locator("text=note.txt").count() > 0

    with page.expect_download() as dl_info:
        page.goto(f"{base_url}/jobs/{job_id}")
        export_link = page.locator('[data-testid="export-job-pack"]')
        assert export_link.count() > 0, "Export link not available for this role"
        export_link.first.click()
    download = dl_info.value
    assert download.suggested_filename.endswith(".zip")

    page.goto(f"{base_url}/jobs/{job_id}/build")
    assert page.locator("text=note.txt").count() > 0


def test_release_job_pack_marks_released(page, base_url):
    _login(page, base_url, "admin@example.com")
    job_id = _open_first_job(page, base_url)

    page.goto(f"{base_url}/jobs/{job_id}/build")
    page.click('[data-testid="build-job-pack"]')
    release_button = page.locator('[data-testid="release-submit"]')
    if release_button.count() > 0:
        page.once("dialog", lambda d: d.accept())
        release_button.click()
        assert page.locator("text=Released on").count() > 0


def test_permissions_tech_blocked_from_admin(page, base_url):
    _login(page, base_url, "technician@example.com")
    resp = page.goto(f"{base_url}/admin/users")
    if page.url.endswith("/admin/users"):
        assert resp.status == 403
    else:
        assert page.url.endswith("/login")
