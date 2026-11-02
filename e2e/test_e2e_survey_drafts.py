"""Browser regressions for survey version and local draft recovery.

The existing e2e server fixture seeds a fresh temporary installation. Run only
where Playwright and its browser are installed and the disposable target is verified.
"""

import re
from playwright.sync_api import expect


def open_survey(page, server_factory, items=6):
    base = server_factory(["--templates", "1", "--jobs", "1", "--items-per-template", str(items)], 5013)
    page.goto(f"{base}/login")
    page.fill('[data-testid="login-username"]', "admin@example.com")
    page.fill('[data-testid="login-password"]', "Password123!")
    page.click('[data-testid="login-submit"]')
    page.goto(f"{base}/jobs")
    page.locator('[data-testid^="job-view-"]').first.click()
    job_id = re.search(r"/jobs/(\d+)", page.url).group(1)
    url = f"{base}/jobs/{job_id}/survey"
    page.goto(url)
    if page.locator('[data-testid="presurvey-form"]').count():
        page.click('[data-testid="presurvey-submit"]')
    page.goto(url)
    assert page.locator('form.survey-form').count() == 1
    return url


def edit_note(page, value):
    page.locator('input[name^="notes_"]').first.evaluate(
        "(el, value) => { el.value=value; el.dispatchEvent(new Event('input', {bubbles:true})); }", value)


def await_autosave(page, old_version):
    expect(page.locator('[name="survey_version"]')).to_have_value(str(old_version + 1), timeout=10000)
    expect(page.locator('#autosave-status')).to_contain_text('Auto-saved')


def test_two_autosaves_manual_save_and_reload(page, server_factory):
    url = open_survey(page, server_factory)
    page.clock.install()
    edit_note(page, 'first')
    page.clock.run_for(46_000)
    await_autosave(page, 0)
    first_version = int(page.locator('input[name="survey_version"]').input_value())
    assert first_version >= 1
    edit_note(page, 'second')
    page.clock.run_for(46_000)
    await_autosave(page, first_version)
    assert int(page.locator('input[name="survey_version"]').input_value()) == first_version + 1
    edit_note(page, 'manual')
    page.locator('[data-testid="survey-save"]').first.click()
    page.goto(url)
    assert page.locator('input[name^="notes_"]').first.input_value() == 'manual'


def test_cross_section_restore_keeps_page_identity(page, server_factory):
    url = open_survey(page, server_factory)
    page.goto(url + '?section=TA')
    page.locator('select[name^="decision_"]').first.select_option('replace')
    a_id = page.locator('[name="visible_ids"]').input_value()
    draft_a = page.evaluate("""() => Object.entries(localStorage).find(([key]) => key.startsWith('reman_draft_org_'))[1]""")
    page.goto(url + '?section=MAN')
    b_id = page.locator('[name="visible_ids"]').input_value()
    assert a_id != b_id
    assert page.locator('#draft-restore').count() == 0  # section A draft remains separate
    page.locator('input[name^="notes_"]').first.evaluate("(el) => { el.value='temporary'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    page.evaluate("""(draft) => {
      const key=Object.keys(localStorage).find(key => key.startsWith('reman_draft_org_') && localStorage[key].includes('temporary'));
      localStorage.setItem(key,draft);
    }""", draft_a)
    page.reload()
    assert page.locator('#draft-restore').count() == 1
    assert page.locator('#draft-restore-btn').count() == 0  # wrong section cannot restore
    assert page.locator('[name="visible_ids"]').input_value() == b_id
    page.locator('#draft-dismiss').click()
    edit_note(page, 'section B saved')
    page.locator('[data-testid="survey-save"]').first.click()
    page.goto(url + '?section=MAN')
    assert page.locator('input[name^="notes_"]').first.input_value() == 'section B saved'
    invalid = page.evaluate("""async (wrong) => {
      const form=document.querySelector('form.survey-form');
      const data=new FormData(form); data.set('visible_ids', wrong); data.set('action','autosave');
      return (await fetch(form.getAttribute('action'), {method:'POST',body:data})).status;
    }""", a_id)
    assert invalid == 400


def test_stale_draft_requires_explicit_review(page, server_factory):
    url = open_survey(page, server_factory)
    with page.expect_popup() as popup:
        page.evaluate("url => window.open(url, '_blank')", url)
    second = popup.value
    first_decision = page.locator('select[name^="decision_"]').first
    second_decision = second.locator('select[name^="decision_"]').first
    first_decision.select_option('replace')
    page.locator('[data-testid="survey-save"]').first.click()
    second_decision.select_option('reuse')
    second.locator('[data-testid="survey-save"]').first.click()
    second.goto(url)
    assert second.locator('#draft-restore').count() == 1
    assert second.locator('#draft-restore-btn').count() == 0
    assert 'Nothing has been merged' in second.locator('#draft-restore').inner_text()
    assert second.locator('select[name^="decision_"]').first.input_value() == 'replace'
    second.close()


def test_paginated_autosave_section_and_reconnect(page, server_factory):
    url = open_survey(page, server_factory, items=500)
    page.locator('a:has-text("Next")').first.click()
    assert 'page=2' in page.url
    assert page.locator('input[name="visible_ids"]').input_value()
    page.clock.install()
    edit_note(page, 'page two auto-save')
    page.clock.run_for(46_000)
    await_autosave(page, 0)
    page.reload()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('page two auto-save')

    page.goto(url + '?section=TA&page=1&per_page=100')
    section_version = int(page.locator('[name="survey_version"]').input_value())
    edit_note(page, 'filtered auto-save')
    page.clock.run_for(46_000)
    await_autosave(page, section_version)
    page.reload()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('filtered auto-save')

    page.goto(url + '?page=2&per_page=100')
    page.context.set_offline(True)
    edit_note(page, 'reconnected page two')
    page.context.set_offline(False)
    expect(page.locator('#autosave-status')).to_contain_text('Draft synced at')
    page.reload()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('reconnected page two')


def test_equivalent_first_page_urls_restore_same_draft(page, server_factory):
    url = open_survey(page, server_factory, items=205)
    edit_note(page, 'unsaved page one')
    page.locator('a:has-text("Next")').first.click()
    page.locator('a:has-text("Prev")').first.click()
    expect(page.locator('#draft-restore-btn')).to_be_visible()
    page.locator('#draft-restore-btn').click()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('unsaved page one')


def test_previous_url_draft_key_is_recoverable(page, server_factory):
    open_survey(page, server_factory, items=205)
    edit_note(page, 'older unsaved draft')
    page.evaluate("""() => {
      const newKey=Object.keys(localStorage).find(key => key.startsWith('reman_draft_org_'));
      const job=location.pathname.split('/')[2];
      localStorage.setItem(`reman_draft_job_${job}_${JSON.stringify(['','1','','classic'])}`,localStorage[newKey]);
      localStorage.removeItem(newKey);
    }""")
    page.locator('a:has-text("Next")').first.click()
    page.locator('a:has-text("Prev")').first.click()
    expect(page.locator('#draft-restore-btn')).to_be_visible()
    page.locator('#draft-restore-btn').click()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('older unsaved draft')
