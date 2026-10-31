import re


def _login(page, base_url, username, password="Password123!"):
    page.goto(f"{base_url}/login")
    page.fill('[data-testid="login-username"]', username)
    page.fill('[data-testid="login-password"]', password)
    page.click('[data-testid="login-submit"]')
    page.wait_for_url(re.compile(r".*/(dashboard|stores).*"), timeout=10000)


def test_permissions_stores_blocked_from_admin(page, base_url):
    _login(page, base_url, "stores@example.com")
    resp = page.goto(f"{base_url}/admin/users")
    if page.url.endswith("/admin/users"):
        assert resp.status == 403
    else:
        assert page.url.endswith("/login")


def test_permissions_stores_can_access_stores(page, base_url):
    _login(page, base_url, "stores@example.com")
    resp = page.goto(f"{base_url}/stores?view=master")
    assert resp.status == 200
