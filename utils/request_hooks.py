from __future__ import annotations

import secrets
import uuid

from flask import abort, g, request


def register_request_hooks(app, *, current_user_fn, set_current_org_id_fn) -> None:
    marker = "_reman_request_hooks_registered"
    if app.extensions.get(marker):
        return

    @app.before_request
    def assign_request_id():
        rid = (request.headers.get("X-Request-ID") or "").strip()
        if not rid:
            rid = uuid.uuid4().hex
        g.request_id = rid
        g.csp_nonce = secrets.token_urlsafe(16)
        user = current_user_fn()
        set_current_org_id_fn(getattr(user, "organization_id", None) if user else None)

    @app.teardown_request
    def clear_tenant_context(_exc):
        set_current_org_id_fn(None)

    @app.after_request
    def attach_request_id(response):
        rid = getattr(g, "request_id", None)
        if rid:
            response.headers["X-Request-ID"] = rid
        return response

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"

        nonce = getattr(g, "csp_nonce", "")
        script_src = "script-src 'self'"
        if nonce:
            script_src += f" 'nonce-{nonce}'"
        csp_parts = [
            "default-src 'self'",
            script_src,
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'self'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)

        if not app.config.get("TESTING") and app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response

    @app.before_request
    def enforce_basic_csrf():
        if not app.config.get("ENFORCE_CSRF", True):
            return
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            host = (request.host_url or "").rstrip("/")
            ref = (request.headers.get("Referer") or "").rstrip("/")
            origin = (request.headers.get("Origin") or "").rstrip("/")
            if host and (ref.startswith(host) or origin.startswith(host)):
                return
            abort(403)

    app.extensions[marker] = True
