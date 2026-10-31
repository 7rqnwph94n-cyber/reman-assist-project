"""Stub PDF renderer for CI and test environments.

Returns a minimal valid PDF document without any system dependencies.
"""
from __future__ import annotations

# Minimal valid single-page PDF (blank A4-ish page).
_STUB_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
    b"startxref\n190\n%%EOF\n"
)


def render_stub_pdf(html: str, base_url: str, css_path: str) -> bytes:
    """Return a minimal valid PDF regardless of input."""
    return _STUB_PDF
