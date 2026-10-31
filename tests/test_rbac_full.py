import pytest
from flask import url_for

from tests.conftest import login_as


ROLE_USERS = {
    "admin": "admin@example.com",
    "office": "office@example.com",
    "tech": "tech@example.com",
    "stores": "stores@example.com",
}

PUBLIC_ENDPOINTS = {
    "auth.index",
    "auth.login",
    "auth.logout",
    "health_check",
    "ready_check",
    "version_info",
}

ENDPOINT_POLICIES = {
    "uploaded_file": set(),
    # Auth admin
    "auth.users_list": {"admin"},
    "auth.user_create": {"admin"},
    "auth.user_delete": {"admin"},
    "auth.change_password": {"admin", "office", "tech", "stores"},
    # Jobs core
    "jobs.dashboard": {"admin", "office", "tech"},
    "jobs.jobs_list": {"admin", "office", "tech"},
    "jobs.job_create": {"admin", "office"},
    "jobs.job_detail": {"admin", "office", "tech"},
    "jobs.job_pre_survey": {"admin", "tech"},
    "survey.job_survey": {"admin", "office", "tech"},
    "survey.seed_survey": {"admin", "office", "tech"},
    "jobs.job_attachments": {"admin", "office", "tech"},
    "jobs.job_pack": {"admin", "office", "tech"},
    "jobs.job_export": {"admin", "office"},
    "jobs.job_report": {"admin", "office"},
    "jobs.job_report_pdf": {"admin", "office"},
    "jobs.job_report_pack": {"admin", "office"},
    "jobs.job_flow_report": {"admin", "office"},
    "jobs.job_flow_report_csv": {"admin", "office"},
    "jobs.job_regenerate_bom": {"admin", "office"},
    "jobs.job_build": {"admin", "tech"},
    "jobs.job_parts_status_summary": {"admin", "tech"},
    # Jobs admin/office actions
    "jobs.release_job": {"admin", "office"},
    # Jobs admin-only actions
    "jobs.admin_autofill_survey": {"admin"},
    "jobs.admin_mark_all_good": {"admin"},
    "jobs.admin_override_status": {"admin"},
    "jobs.kpi_dashboard": {"admin"},
    "jobs.system_status": {"admin"},
    # Parts
    "parts.job_parts": {"admin", "office"},
    "parts.job_parts_procurement": {"admin", "office"},
    "parts.job_parts_export": {"admin", "office"},
    # Stores
    "stores.stores_hub": {"admin", "office", "stores"},
    "stores.stores_for_template": {"admin", "office", "stores"},
    "stores.picklist_detail": {"admin", "office", "stores"},
    "stores.update_picklist_status": {"admin", "office", "stores"},
    "stores.stores_update": {"admin", "stores"},
    "stores.stores_seed": {"admin"},
    "stores.stores_barcodes_import": {"admin", "stores"},
    "stores.stores_barcodes_update": {"admin", "stores"},
    # Templates admin
    "templates_bp.templates_list": {"admin"},
    "templates_bp.template_create": {"admin"},
    "templates_bp.template_edit": {"admin"},
    "templates_bp.template_delete": {"admin"},
    "templates_bp.template_measurements": {"admin"},
    "templates_bp.template_presurvey": {"admin"},
    "templates_bp.template_costing_upload": {"admin"},
    "templates_bp.template_wizard": {"admin"},
    # Costing
    "costing.job_costing": {"admin", "office"},
    "costing.job_costing_upload": {"admin", "office"},
    "costing.job_costing_use_upload": {"admin", "office"},
    "costing.job_costing_download": {"admin", "office"},
    "costing.costing_json": {"admin", "office"},
    "costing.export_costing": {"admin", "office"},
    "costing.export_costing_dmt": {"admin", "office"},
    "costing.bind_costing": {"admin", "office"},
    "costing.costing_catalogue": {"admin"},
    # Epicor
    "epicor.epicor_settings": {"admin"},
    # QuickBooks
    "quickbooks.quickbooks_settings": {"admin"},
    "quickbooks.quickbooks_connect": {"admin"},
    "quickbooks.quickbooks_callback": {"admin"},
    "quickbooks.quickbooks_disconnect": {"admin"},
    "quickbooks.quickbooks_test": {"admin"},
    "quickbooks.quickbooks_save_settings": {"admin"},
    "quickbooks.sync_job_invoice": {"admin", "office"},
    "quickbooks.job_quickbooks_status": {"admin", "office"},
    "quickbooks.sync_job_expenses": {"admin", "office"},
    "quickbooks.quickbooks_logs": {"admin", "office"},
    # Illustrations
    "illustrations_bp.illustration_wizard": {"admin"},
    "illustrations_bp.api_section_illustrations": {"admin", "office", "tech"},
    "illustrations_bp.api_create_illustration": {"admin"},
    "illustrations_bp.api_update_illustration": {"admin"},
    "illustrations_bp.api_import_parts": {"admin"},
    "illustrations_bp.api_update_parts": {"admin"},
    "illustrations_bp.api_link_illustration": {"admin"},
    "illustrations_bp.api_reorder_illustrations": {"admin"},
    "illustrations_bp.api_publish_illustration": {"admin"},
    "illustrations_bp.api_set_pos_label": {"admin"},
    "illustrations_bp.api_delete_pos_label": {"admin"},
    "illustrations_bp.api_create_hotspot": {"admin"},
    "illustrations_bp.api_replace_hotspots": {"admin"},
    "illustrations_bp.api_delete_hotspot": {"admin"},
}


def _build_url(app, rule, rbac_ids):
    kwargs = {arg: rbac_ids[arg] for arg in rule.arguments}
    with app.test_request_context():
        return url_for(rule.endpoint, **kwargs)


def _expected_status_ok(allowed: bool):
    if allowed:
        return {200, 302, 400, 404}
    return {302, 403}


def _method_for_rule(rule):
    if "GET" in rule.methods:
        return "GET"
    if "PUT" in rule.methods:
        return "PUT"
    if "PATCH" in rule.methods:
        return "PATCH"
    if "DELETE" in rule.methods:
        return "DELETE"
    return "POST"


def _resolved_policy(endpoint):
    if endpoint in PUBLIC_ENDPOINTS:
        return set(ROLE_USERS.keys())
    return ENDPOINT_POLICIES.get(endpoint)


def _coverage_report(app_for_tests):
    endpoints = []
    for rule in app_for_tests.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        endpoints.append(rule.endpoint)
    missing = [ep for ep in endpoints if ep not in PUBLIC_ENDPOINTS and ep not in ENDPOINT_POLICIES]
    covered = [ep for ep in endpoints if ep in PUBLIC_ENDPOINTS or ep in ENDPOINT_POLICIES]
    lines = [
        "RBAC policy coverage report",
        f"Total endpoints: {len(endpoints)}",
        f"Covered: {len(covered)}",
        f"Missing: {len(missing)}",
        "",
    ]
    if missing:
        lines.append("Missing endpoints:")
        lines.extend(sorted(missing))
    else:
        lines.append("All endpoints covered.")
    return "\n".join(lines)


def test_rbac_policy_covers_all_routes(app_for_tests):
    missing = []
    for rule in app_for_tests.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if rule.endpoint in PUBLIC_ENDPOINTS:
            continue
        if rule.endpoint not in ENDPOINT_POLICIES:
            missing.append(rule.endpoint)
    assert not missing, f"Missing RBAC policy for: {sorted(missing)}"


def test_rbac_policy_report(app_for_tests):
    report = _coverage_report(app_for_tests)
    assert report
    print(report)


@pytest.mark.parametrize("role", sorted(ROLE_USERS.keys()))
def test_rbac_full_matrix(app_for_tests, client, seed_users, rbac_ids, role):
    username = ROLE_USERS[role]
    login_as(client, username=username)

    for rule in app_for_tests.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        policy = _resolved_policy(rule.endpoint)
        assert policy is not None, f"No RBAC policy for {rule.endpoint}"

        url = _build_url(app_for_tests, rule, rbac_ids)
        method = _method_for_rule(rule)
        res = client.open(url, method=method, data={})
        allowed = role in policy
        assert res.status_code in _expected_status_ok(allowed), (
            f"{rule.endpoint} {method} role={role} status={res.status_code}"
        )
