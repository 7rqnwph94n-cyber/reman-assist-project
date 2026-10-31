import os
import pytest

from tests.conftest import login_as


def test_report_view_allowed_for_admin(app_for_tests, client, seed_users, job_id):
    login_as(client, username="admin@example.com")
    res = client.get(f"/jobs/{job_id}/report")
    assert res.status_code == 200


def test_report_view_denied_for_tech(app_for_tests, client, seed_users, job_id):
    login_as(client, username="tech@example.com")
    res = client.get(f"/jobs/{job_id}/report")
    assert res.status_code in {302, 403}


def test_report_pdf_download(app_for_tests, client, seed_users, job_id):
    login_as(client, username="office@example.com")
    res = client.get(f"/jobs/{job_id}/report.pdf")
    assert res.status_code == 200
    assert res.headers.get("Content-Type", "").startswith("application/pdf")


def test_report_customer_view_hides_internal(app_for_tests, client, seed_users, job_id):
    login_as(client, username="office@example.com")
    res = client.get(f"/jobs/{job_id}/report?view=customer")
    assert res.status_code == 200
    body = res.data.decode("utf-8")
    assert "Customer view" in body
    assert "Uploaded by" not in body


def test_report_pack_zip(app_for_tests, client, seed_users, job_id):
    login_as(client, username="office@example.com")
    res = client.get(f"/jobs/{job_id}/export.zip")
    assert res.status_code == 200
    assert res.headers.get("Content-Type", "").startswith("application/zip")
    import zipfile
    import io

    zf = zipfile.ZipFile(io.BytesIO(res.data))
    names = set(zf.namelist())
    assert any(name.endswith("_Report.pdf") for name in names)
    assert any(
        (name.startswith("BOM_") or name.startswith("PartsList_"))
        and name.endswith(".csv")
        for name in names
    )
    assert "attachments_index.csv" in names
