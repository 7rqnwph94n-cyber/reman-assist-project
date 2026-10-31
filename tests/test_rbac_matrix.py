import pytest
from flask import url_for

from models import RoleEnum
from tests.conftest import login_as


RBAC_MATRIX = [
    ("jobs.dashboard", {}, {"admin", "office", "tech"}, {"stores"}),
    ("jobs.job_create", {}, {"admin", "office"}, {"tech", "stores"}),
    ("jobs.jobs_list", {}, {"admin", "office", "tech"}, {"stores"}),
    ("templates_bp.templates_list", {}, {"admin"}, {"office", "tech", "stores"}),
    ("stores.stores_hub", {"view": "master"}, {"admin", "office", "stores"}, {"tech"}),
    ("auth.users_list", {}, {"admin"}, {"office", "tech", "stores"}),
    ("epicor.epicor_settings", {}, {"admin"}, {"office", "tech", "stores"}),
]


@pytest.mark.parametrize("route_name,kwargs,allowed,forbidden", RBAC_MATRIX)
def test_rbac_routes(app_for_tests, client, seed_users, job_id, route_name, kwargs, allowed, forbidden):
    with app_for_tests.test_request_context():
        url = url_for(route_name, **kwargs)

        for role in allowed:
            username = f"{role}@example.com"
            login_as(client, username=username)
            res = client.get(url, follow_redirects=False)
            allowed_codes = {200, 302}
            if route_name == "jobs.job_export":
                # Feature-flagged legacy export may be disabled, returning 404 even for allowed roles.
                allowed_codes.add(404)
            assert res.status_code in allowed_codes

    for role in forbidden:
        username = f"{role}@example.com"
        login_as(client, username=username)
        res = client.get(url, follow_redirects=False)
        assert res.status_code in {403, 302}


@pytest.mark.parametrize(
    "route_name,kwargs,allowed,forbidden",
    [
        ("survey.job_survey", {"job_id": 1}, {"admin", "office", "tech"}, {"stores"}),
        ("parts.job_parts", {"job_id": 1}, {"admin", "office"}, {"tech", "stores"}),
        ("jobs.job_build", {"job_id": 1}, {"admin", "tech"}, {"office", "stores"}),
        ("jobs.job_attachments", {"job_id": 1}, {"admin", "office", "tech"}, {"stores"}),
        ("jobs.job_export", {"job_id": 1}, {"admin", "office"}, {"tech", "stores"}),
    ],
)
def test_rbac_job_routes(app_for_tests, client, seed_users, job_id, route_name, kwargs, allowed, forbidden):
    with app_for_tests.test_request_context():
        kwargs = dict(kwargs)
        kwargs["job_id"] = job_id
        url = url_for(route_name, **kwargs)

    allow_404 = {"jobs.job_export"}
    allowed_statuses = {200, 302}
    if route_name in allow_404:
        allowed_statuses.add(404)

    for role in allowed:
        username = f"{role}@example.com"
        login_as(client, username=username)
        res = client.get(url, follow_redirects=False)
        assert res.status_code in allowed_statuses

    for role in forbidden:
        username = f"{role}@example.com"
        login_as(client, username=username)
        res = client.get(url, follow_redirects=False)
        assert res.status_code in {403, 302}
