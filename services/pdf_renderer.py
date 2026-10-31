from __future__ import annotations

import os
import sys
from typing import Optional

from flask import current_app


def _ensure_darwin_lib_path() -> None:
    if sys.platform != "darwin":
        return
    candidates = ["/opt/homebrew/lib", "/usr/local/lib"]
    existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    paths = [p for p in candidates if p not in existing]
    if paths:
        os.environ["DYLD_LIBRARY_PATH"] = ":".join([existing] + paths if existing else paths)
    # Ensure fontconfig has a writable cache path in restricted environments.
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
    os.environ.setdefault("FONTCONFIG_PATH", "/opt/homebrew/etc/fonts")


def _inline_report_css(html: str, css_path: str, base_url: str) -> str:
    try:
        with open(css_path, "r", encoding="utf-8") as handle:
            css = handle.read()
    except OSError:
        css = ""

    base_tag = f'<base href="{base_url}">'
    style_tag = f"<style>{css}</style>" if css else ""

    if "<head>" in html:
        return html.replace("<head>", f"<head>{base_tag}{style_tag}", 1)
    return f"<head>{base_tag}{style_tag}</head>{html}"


def _render_with_weasyprint(html: str, base_url: str, css_path: str) -> bytes:
    _ensure_darwin_lib_path()
    from weasyprint import HTML, CSS  # type: ignore

    return HTML(string=html, base_url=base_url).write_pdf(
        stylesheets=[CSS(filename=css_path)]
    )


def _render_with_playwright(html: str, base_url: str, css_path: str) -> bytes:
    from playwright.sync_api import sync_playwright  # type: ignore

    html = _inline_report_css(html, css_path, base_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.emulate_media(media="print")
        pdf = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"},
        )
        browser.close()
    return pdf


def get_pdf_renderer_status() -> dict[str, object]:
    status: dict[str, object] = {"ready": False, "engines": {}}
    engines: dict[str, str] = {}
    _ensure_darwin_lib_path()
    try:
        import weasyprint  # type: ignore  # noqa: F401

        engines["weasyprint"] = "ok"
    except Exception as exc:
        engines["weasyprint"] = f"unavailable: {exc}"
    try:
        import playwright.sync_api  # type: ignore  # noqa: F401

        engines["playwright"] = "ok"
    except Exception as exc:
        engines["playwright"] = f"unavailable: {exc}"
    engines["stub"] = "ok"
    status["engines"] = engines
    status["ready"] = any(v == "ok" for v in engines.values())
    return status


def render_report_pdf(
    html: str,
    base_url: str,
    css_path: str,
    engine: Optional[str] = None,
) -> bytes:
    primary = (engine or current_app.config.get("PDF_RENDERER") or "weasyprint").lower()
    fallback = (current_app.config.get("PDF_RENDERER_FALLBACK") or "playwright").lower()

    errors = []
    for name in (primary, fallback):
        if name == "weasyprint":
            try:
                return _render_with_weasyprint(html, base_url, css_path)
            except Exception as exc:  # pragma: no cover - depends on system libs
                current_app.logger.exception("WeasyPrint failed")
                errors.append(
                    "weasyprint unavailable (install system deps; see README.md)"
                )
        elif name == "playwright":
            try:
                return _render_with_playwright(html, base_url, css_path)
            except Exception as exc:  # pragma: no cover - depends on system libs
                current_app.logger.exception("Playwright PDF failed")
                errors.append(
                    "playwright unavailable (pip install playwright && python -m playwright install chromium; see README.md)"
                )
        elif name == "stub":
            from services.pdf_renderer_stub import render_stub_pdf

            return render_stub_pdf(html, base_url, css_path)

    message = "PDF render failed. " + "; ".join(errors)
    raise RuntimeError(message)
