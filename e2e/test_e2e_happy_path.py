import re
import time


def _login(page, base_url, username, password="Password123!"):
    page.goto(f"{base_url}/login")
    page.fill('[data-testid="login-username"]', username)
    page.fill('[data-testid="login-password"]', password)
    page.click('[data-testid="login-submit"]')
    page.wait_for_url(re.compile(r".*/(dashboard|stores).*"), timeout=10000)


def _select_first_option(page, selector):
    options = page.locator(f"{selector} option").all()
    for opt in options:
        val = opt.get_attribute("value")
        if val and val.strip():
            page.select_option(selector, value=val)
            return
    raise AssertionError("No selectable options found")


def test_happy_path_job_flow(page, base_url):
    job_number = f"E2E-{int(time.time())}"

    # Office creates job
    _login(page, base_url, "office@example.com")
    page.goto(f"{base_url}/jobs/create")
    page.fill('[data-testid="job-number"]', job_number)
    page.fill('[data-testid="customer-name"]', "E2E Customer")
    page.fill('[data-testid="engine-type"]', "E2E Engine")
    _select_first_option(page, '[data-testid="template-select"]')
    page.click('[data-testid="create-job-submit"]')

    # Open job detail
    page.click(f'[data-testid="job-view-{job_number}"]')
    page.click('[data-testid="open-survey"]')

    # Admin completes pre-survey + survey
    page.goto(f"{base_url}/logout")
    _login(page, base_url, "admin@example.com")
    page.goto(f"{base_url}/jobs")
    page.click(f'[data-testid="job-view-{job_number}"]')
    page.click('[data-testid="open-survey"]')

    # Pre-survey gate
    if page.locator('[data-testid="presurvey-form"]').count() > 0:
        page.click('[data-testid="presurvey-submit"]')

    # Fill decisions + measurements
    for sel in page.locator('select[name^="decision_"]').all():
        if sel.is_disabled():
            continue
        sel.select_option("replace", force=True)
    for inp in page.locator('input[name^="measurement_value_"]').all():
        inp.fill("15")
    for inp in page.locator('input[name^="spec_min_"]').all():
        inp.fill("10")
    for inp in page.locator('input[name^="spec_max_"]').all():
        inp.fill("20")
    page.click('[data-testid="survey-complete"]')

    # Parts page: save list
    if page.locator('[data-testid="parts-form"]').count() > 0:
        page.click('[data-testid="parts-save"]')

    # Job pack release (may be blocked by NCs)
    page.goto(f"{base_url}/jobs")
    page.click(f'[data-testid="job-view-{job_number}"]')
    page.click('[data-testid="open-build"]')
    page.click('[data-testid="build-job-pack"]')
