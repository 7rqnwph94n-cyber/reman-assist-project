from models import Template, Job


def _login(client, username="admin@example.com", password="Password123!"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_sql_injection_attempts(client, seed_basic):
    payloads = [
        "' OR '1'='1",
        "admin'--",
        "' OR 1=1--",
        "'; DROP TABLE users;--",
        "1' UNION SELECT null,null,null--",
        "admin' AND '1'='1",
    ]

    for payload in payloads:
        res = client.post(
            "/login",
            data={"username": payload, "password": payload},
            follow_redirects=False,
        )
        location = (res.headers.get("Location") or "").lower()
        assert "/dashboard" not in location


def test_login_rate_limiting(client, seed_basic):
    last = None
    for i in range(10):
        last = client.post(
            "/login",
            data={"username": "attacker@example.com", "password": f"wrong-{i}"},
            follow_redirects=True,
        )
    assert last is not None
    body = last.get_data(as_text=True)
    assert "Too many login attempts" in body


def test_xss_payload_escaped_in_jobs(client, app_for_tests, seed_basic):
    _login(client)
    with app_for_tests.app_context():
        template = Template.query.first()
        assert template is not None
        template_id = template.id

    payload = "<script>alert('xss')</script>"
    job_number = "SEC-XSS-001"
    client.post(
        "/jobs/create",
        data={
            "job_number": job_number,
            "customer_name": payload,
            "engine_type": "SEC",
            "serial_number": "SEC-1",
            "template_id": str(template_id),
        },
        follow_redirects=True,
    )

    with app_for_tests.app_context():
        job = Job.query.filter_by(job_number=job_number).first()
        assert job is not None
        job_id = job.id

    detail = client.get(f"/jobs/{job_id}")
    page = detail.get_data(as_text=True)
    assert job_number in page
    assert payload not in page


def test_csrf_protection_when_enabled(client, app_for_tests, seed_basic):
    _login(client)
    app_for_tests.config["ENFORCE_CSRF"] = True

    with app_for_tests.app_context():
        template = Template.query.first()
        assert template is not None
        template_id = template.id

    res = client.post(
        "/jobs/create",
        data={
            "job_number": "SEC-CSRF-001",
            "customer_name": "CSRF Test",
            "engine_type": "SEC",
            "serial_number": "SEC-CSRF",
            "template_id": str(template_id),
        },
        follow_redirects=False,
    )
    assert res.status_code == 403


def test_path_traversal_blocked(client, seed_basic):
    _login(client)
    res = client.get("/uploads/../../../etc/passwd")
    assert res.status_code in {403, 404}


def test_security_headers_present(client):
    res = client.get("/")
    assert "X-Content-Type-Options" in res.headers
    assert "X-Frame-Options" in res.headers
    assert "Content-Security-Policy" in res.headers
