import re


def test_big_job_survey_load(page, server_factory):
    base_url = server_factory(
        seed_args=["--templates", "1", "--jobs", "1", "--items-per-template", "120", "--bom-lines-per-job", "120"],
        port=5010,
    )
    page.goto(f"{base_url}/login")
    page.fill('[data-testid="login-username"]', "admin@example.com")
    page.fill('[data-testid="login-password"]', "Password123!")
    page.click('[data-testid="login-submit"]')
    page.wait_for_url(re.compile(r".*/(dashboard|stores).*"), timeout=10000)

    page.goto(f"{base_url}/jobs")
    page.locator('[data-testid^="job-view-"]').first.click()
    page.click('[data-testid="open-survey"]')

    # Pre-survey gate may appear for seeded jobs
    if page.locator('[data-testid="presurvey-form"]').count() > 0:
        page.click('[data-testid="presurvey-submit"]')

    selects = page.locator('select[name^="decision_"]')
    assert selects.count() >= 100
