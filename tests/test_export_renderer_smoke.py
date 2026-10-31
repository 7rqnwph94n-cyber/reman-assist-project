import pytest

from services.pdf_renderer import render_report_pdf


def test_pdf_renderer_smoke(app_for_tests):
    with app_for_tests.app_context():
        html = "<html><body><h1>Smoke</h1></body></html>"
        pdf = render_report_pdf(
            html,
            base_url="http://localhost/",
            css_path="static/css/report.css",
        )
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 100
