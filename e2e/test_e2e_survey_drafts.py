"""Browser regressions for survey version and local draft recovery.

The existing e2e server fixture seeds a fresh temporary installation. Run only
where Playwright and its browser are installed and the disposable target is verified.
"""

import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
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


def edit_note_via_popup(page, value):
    page.once('dialog', lambda dialog: dialog.accept(value))
    page.locator('.notes-btn').first.click()
    expect(page.locator('input[name^="notes_"]').first).to_have_value(value)


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
    first_decision = page.locator('select[name^="decision_"]').first
    first_decision.select_option('reuse' if first_decision.input_value() == 'replace' else 'replace')
    a_id = page.locator('[name="visible_ids"]').input_value()
    draft_a = page.evaluate("""() => Object.entries(localStorage).find(([key]) => key.startsWith('reman_draft_org_'))[1]""")
    assert page.evaluate('(draft) => JSON.parse(draft).changed.length > 0', draft_a)
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
    second.wait_for_load_state('load')
    expect(second.locator('form.survey-form')).to_be_visible()
    expect(second.locator('[name="survey_version"]')).to_have_value('0')
    assert second.locator('#draft-restore').count() == 0
    first_decision = page.locator('select[name^="decision_"]').first
    second_decision = second.locator('select[name^="decision_"]').first
    first_decision.select_option('replace')
    page.locator('[data-testid="survey-save"]').first.click()
    expect(page).to_have_url(re.compile(r'save_ack='))
    expect(page.locator('[name="survey_version"]')).to_have_value('1')
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


def test_manual_saves_do_not_protect_accepted_drafts_or_lock_other_tab(page, server_factory):
    url = open_survey(page, server_factory)
    with page.expect_popup() as popup:
        page.evaluate("url => window.open(url, '_blank')", url)
    other = popup.value
    other.wait_for_load_state('load')
    expect(other.locator('form.survey-form')).to_be_visible()
    expect(other.locator('[name="survey_version"]')).to_have_value('0')
    assert other.locator('#draft-restore').count() == 0
    acknowledged_ids = set()

    for version, (decision, note) in enumerate([
        ('reuse', 'good inspection'),
        ('replace', 'replacement inspection'),
        ('scrap', 'missing inspection'),
    ], 1):
        page.locator('select[name^="decision_"]').first.select_option(decision)
        edit_note_via_popup(page, note)
        page.locator('[data-testid="survey-save"]').first.click()
        acknowledged_id = parse_qs(urlsplit(page.url).query)['save_ack'][0]
        assert UUID(acknowledged_id).version == 4
        assert acknowledged_id not in acknowledged_ids
        acknowledged_ids.add(acknowledged_id)
        expect(page.locator('[name="survey_version"]')).to_have_value(str(version))
        expect(page.locator('select[name^="decision_"]').first).to_have_value(decision)
        expect(page.locator('input[name^="notes_"]').first).to_have_value(note)
        assert page.locator('#draft-restore').count() == 0
        assert page.locator('[data-testid="survey-save"]').first.is_enabled()
        assert other.locator('#draft-restore').count() == 0
        assert other.locator('[data-testid="survey-save"]').first.is_enabled()
        page.goto(url)
        expect(page.locator('input[name^="notes_"]').first).to_have_value(note)
        assert page.locator('#draft-restore').count() == 0
    other.close()


def test_normalised_manual_saves_and_note_only_draft_recovery(page, server_factory):
    url = open_survey(page, server_factory)
    edit_note_via_popup(page, 'note only')
    expect(page.locator('#autosave-status')).to_contain_text('Auto-save pending')
    page.reload()  # before the 45-second auto-save timer
    expect(page.locator('#draft-restore-btn')).to_be_visible()
    page.locator('#draft-restore-btn').click()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('note only')
    page.locator('[data-testid="survey-save"]').first.click()
    assert page.locator('#draft-restore').count() == 0
    assert page.locator('[data-testid="survey-save"]').first.is_enabled()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('note only')

    edit_note_via_popup(page, 'worn  ')
    page.locator('[data-testid="survey-save"]').first.click()
    expect(page.locator('input[name^="notes_"]').first).to_have_value('worn')
    assert page.locator('#draft-restore').count() == 0
    assert page.locator('[data-testid="survey-save"]').first.is_enabled()

    measured = page.locator('input[name^="measurement_value_"]').first
    assert measured.count() == 1
    measured.fill('10.02')
    page.locator('[data-testid="survey-save"]').first.click()
    expect(page.locator('input[name^="measurement_value_"]').first).to_have_value('10.0200')
    assert page.locator('#draft-restore').count() == 0
    assert page.locator('[data-testid="survey-save"]').first.is_enabled()
    page.goto(url)
    expect(page.locator('input[name^="notes_"]').first).to_have_value('worn')
    expect(page.locator('input[name^="measurement_value_"]').first).to_have_value('10.0200')


def test_add_row_acknowledges_save_and_allows_next_edit(page, server_factory):
    url = open_survey(page, server_factory)
    first = page.locator('select[name^="decision_"]').first
    original_row_id = first.get_attribute('data-item-id')
    original_decision = page.locator(f'select[name="decision_{original_row_id}"]')
    decision = 'reuse' if first.input_value() == 'replace' else 'replace'
    first.select_option(decision)
    page.locator('input[name="new_name"]').fill('Added inspection part')
    page.locator('[data-testid="survey-add-row"]').first.click()
    expect(page.locator('[name="survey_version"]')).to_have_value('1')
    expect(page.get_by_text('Added inspection part')).to_be_visible()
    expect(original_decision).to_have_value(decision)
    assert page.locator('#draft-restore').count() == 0
    assert page.locator('[data-testid="survey-save"]').first.is_enabled()
    edit_note_via_popup(page, 'second edit after add row')
    page.locator('[data-testid="survey-save"]').first.click()
    expect(page.locator('[name="survey_version"]')).to_have_value('2')
    assert page.locator('#draft-restore').count() == 0
    page.goto(url)
    expect(page.locator('input[name^="notes_"]').first).to_have_value('second edit after add row')


def test_refused_and_successful_complete_acknowledge_only_committed_changes(page, server_factory):
    def open_sections():
        collapsed = page.locator('details.survey-section:not([open]) > summary')
        while collapsed.count():
            collapsed.first.click()

    url = open_survey(page, server_factory)
    page.goto(url + '?section=MAN')
    edit_note(page, 'separate section draft')
    other_key = page.evaluate("""() => Object.keys(localStorage).find(key =>
      key.startsWith('reman_draft_org_') && localStorage[key].includes('separate section draft'))""")
    assert other_key
    page.goto(url)
    open_sections()
    for select in page.locator('select[name^="decision_"]').all():
        select.select_option('')
    page.locator('select[name^="decision_"]').first.select_option('replace')
    page.locator('[data-testid="survey-complete"]').first.click()
    expect(page.locator('[name="survey_version"]')).to_have_value('1')
    expect(page.locator('select[name^="decision_"]').first).to_have_value('replace')
    expect(page.get_by_text('Cannot complete', exact=False)).to_be_visible()
    assert page.locator('#draft-restore').count() == 0
    assert page.locator('[data-testid="survey-save"]').first.is_enabled()

    open_sections()
    for select in page.locator('select[name^="decision_"]').all():
        select.select_option('replace')
    page.locator('input[name^="measurement_value_"]').first.fill('')
    page.locator('[data-testid="survey-complete"]').first.click()
    expect(page.locator('[name="survey_version"]')).to_have_value('2')
    expect(page.get_by_text('measurement-required', exact=False)).to_be_visible()
    assert page.locator('#draft-restore').count() == 0
    assert page.locator('[data-testid="survey-save"]').first.is_enabled()

    open_sections()
    page.locator('input[name^="measurement_value_"]').first.fill('10.02')
    saved_key = page.evaluate("""() => {
      const ids = document.querySelector('form.survey-form [name="visible_ids"]').value;
      return Object.keys(localStorage).find(key => {
        if (!key.startsWith('reman_draft_org_')) return false;
        const draft = JSON.parse(localStorage.getItem(key));
        return draft.fields?.visible_ids === ids;
      });
    }""")
    assert saved_key and saved_key != other_key
    page.locator('[data-testid="survey-complete"]').first.click()
    expect(page).to_have_url(re.compile(r'/jobs/\d+/parts$'))
    assert page.evaluate('(key) => localStorage.getItem(key)', saved_key) is not None
    page.goto(url)  # readonly survey consumes the committed completion receipt
    assert page.evaluate('(key) => localStorage.getItem(key)', saved_key) is None
    assert page.evaluate('(key) => localStorage.getItem(key)', other_key) is not None
    assert page.locator('#draft-restore').count() == 0


def test_cancelled_notes_popup_does_not_create_draft(page, server_factory):
    open_survey(page, server_factory)
    before = page.evaluate("() => Object.keys(localStorage).filter(key => key.startsWith('reman_draft_org_'))")
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('.notes-btn').first.click()
    assert page.evaluate("() => Object.keys(localStorage).filter(key => key.startsWith('reman_draft_org_'))") == before


def test_save_ack_does_not_clear_newer_tab_draft(page, server_factory):
    url = open_survey(page, server_factory)
    with page.expect_popup() as popup:
        page.evaluate("url => window.open(url, '_blank')", url)
    other = popup.value
    other.wait_for_load_state('load')
    expect(other.locator('form.survey-form')).to_be_visible()
    note_name = page.locator('input[name^="notes_"]').first.get_attribute('name')
    intercepted = []

    def add_newer_draft(route):
        if route.request.method != 'POST':
            route.continue_()
            return
        response = route.fetch(max_redirects=0)
        assert response.status == 302
        assert 'save_ack=' in response.headers['location']
        intercepted.append(response.headers['location'])
        # The server has committed. Pause delivery of its redirect while the
        # other tab writes a newer local snapshot under the same page key.
        other.evaluate("""(name) => {
          const key=Object.keys(localStorage).find(key => key.startsWith('reman_draft_org_'));
          const draft=JSON.parse(localStorage.getItem(key));
          delete draft.save_id;
          draft.fields[name]='newer unsaved inspection';
          draft.changed=[name];
          localStorage.setItem(key, JSON.stringify(draft));
        }""", note_name)
        route.fulfill(response=response)

    page.route('**/jobs/*/survey*', add_newer_draft)
    edit_note_via_popup(page, 'accepted inspection')
    page.locator('[data-testid="survey-save"]').first.click()
    assert len(intercepted) == 1
    expect(page.locator('input[name^="notes_"]').first).to_have_value('accepted inspection')
    expect(page.locator('#draft-restore')).to_contain_text('newer unsaved inspection')
    assert page.evaluate("""() => {
      const key=Object.keys(localStorage).find(key => key.startsWith('reman_draft_org_'));
      return JSON.parse(localStorage.getItem(key)).fields[document.querySelector('input[name^="notes_"]').name];
    }""") == 'newer unsaved inspection'
    page.reload()
    expect(page.locator('#draft-restore')).to_contain_text('newer unsaved inspection')
    other.close()


def test_rejected_measurement_save_retains_local_draft(page, server_factory):
    open_survey(page, server_factory)
    original = page.locator('input[name^="measurement_value_"]').first.input_value()
    page.locator('input[name^="measurement_value_"]').first.fill('1.2.3')
    page.locator('[data-testid="survey-save"]').first.click()
    expect(page.locator('#draft-restore-btn')).to_be_visible()
    assert 'save_ack=' not in page.url
    expect(page.locator('input[name^="measurement_value_"]').first).to_have_value(original)
    page.locator('#draft-restore-btn').click()
    expect(page.locator('input[name^="measurement_value_"]').first).to_have_value('1.2.3')


def test_stale_inspection_draft_survives_typing_navigation_and_explicit_discard(page, server_factory):
    url = open_survey(page, server_factory, items=205)
    with page.expect_popup() as popup:
        page.evaluate("url => window.open(url, '_blank')", url)
    other = popup.value
    decision = other.locator('select[name^="decision_"]').first
    note = other.locator('input[name^="notes_"]').first
    decision_name = decision.get_attribute('name')
    note_name = note.get_attribute('name')

    decision.select_option('scrap')
    edit_note_via_popup(other, 'crack 2mm')
    page.locator('select[name^="decision_"]').first.select_option('replace')
    page.locator('[data-testid="survey-save"]').first.click()
    expect(page.locator('select[name^="decision_"]').first).to_have_value('replace')
    assert page.locator('#draft-restore').count() == 0  # accepted save needs no review
    assert other.locator('#draft-restore').count() == 0
    assert other.locator('[data-testid="survey-save"]').first.is_enabled()

    other.locator('[data-testid="survey-save"]').first.click()
    expect(other.locator('#draft-restore')).to_be_visible()
    expect(other.locator('#draft-restore')).to_contain_text('crack 2mm')
    assert other.locator('#draft-restore-btn').count() == 0
    draft = other.evaluate("""() => {
      const key=Object.keys(localStorage).find(key => key.startsWith('reman_draft_org_'));
      return {key, value: JSON.parse(localStorage.getItem(key))};
    }""")
    assert draft['value']['fields'][decision_name] == 'scrap'
    assert draft['value']['fields'][note_name] == 'crack 2mm'

    # Editing is paused. Exercise the hidden backing field's input handler as
    # well, so incidental events cannot replace the protected draft.
    assert decision.is_disabled()
    note.evaluate("(el) => { el.value='New typing while draft review is open'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    other.reload()
    expect(other.locator('#draft-restore')).to_contain_text('crack 2mm')
    assert other.evaluate('(key) => JSON.parse(localStorage.getItem(key))', draft['key']) == draft['value']

    other.context.set_offline(True)
    other.context.set_offline(False)
    expect(other.locator('#draft-restore')).to_be_visible()
    assert other.evaluate('(key) => JSON.parse(localStorage.getItem(key))', draft['key']) == draft['value']

    other.locator('a:has-text("Next")').first.click()
    edit_note(other, 'separate page two draft')
    page_two_key = other.evaluate("""() => Object.keys(localStorage).find(key =>
      key.startsWith('reman_draft_org_') && localStorage[key].includes('separate page two draft'))""")
    assert page_two_key and page_two_key != draft['key']
    other.locator('a:has-text("Prev")').first.click()
    expect(other.locator('#draft-restore')).to_contain_text('crack 2mm')
    assert other.evaluate('(key) => JSON.parse(localStorage.getItem(key))', draft['key']) == draft['value']

    other.locator('#draft-dismiss').click()
    assert other.evaluate('(key) => localStorage.getItem(key)', draft['key']) is None
    assert other.evaluate('(key) => localStorage.getItem(key)', page_two_key) is not None
    other.reload()
    assert other.locator('#draft-restore').count() == 0
    expect(other.locator('select[name^="decision_"]').first).to_have_value('replace')
    other.close()
