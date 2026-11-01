import io
import os
import types
import pytest

from models import (
    db,
    Organization,
    User,
    RoleEnum,
    Template,
    TemplateItem,
    Job,
    SurveyItem,
    PartRequirement,
    DecisionEnum,
    JobStatusEnum,
    Attachment,
)
from werkzeug.security import generate_password_hash
from services.job_services import ensure_survey_from_template, change_job_status
from services.bom import regenerate_bom_for_job
from services.pdf_renderer import render_report_pdf
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def app_instance(tmp_path, test_app_factory):
    app = test_app_factory(database_uri=f"sqlite:///{tmp_path / 'pilot.db'}")
    with app.app_context():
        yield app


@pytest.fixture()
def client(app_instance):
    return app_instance.test_client()


def _seed_org_users(app_instance):
    with app_instance.app_context():
        org = Organization(name="Pilot Org", slug="pilot-org")
        db.session.add(org)
        db.session.flush()
        users = {}
        for role in (RoleEnum.ADMIN, RoleEnum.OFFICE, RoleEnum.TECHNICIAN, RoleEnum.STORES):
            u = User(
                username=f"{role.value}@example.com",
                password_hash=generate_password_hash("Password123!"),
                role=role,
                organization_id=org.id,
            )
            db.session.add(u)
            users[role.value] = u
        db.session.commit()
        return org.id, {k: v.id for k, v in users.items()}


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_auth_boundaries(app_instance, client):
    _org_id, users = _seed_org_users(app_instance)
    _login(client, users[RoleEnum.ADMIN.value])
    res = client.get("/admin/templates")
    assert res.status_code == 200

    _login(client, users[RoleEnum.TECHNICIAN.value])
    res = client.get("/admin/templates")
    assert res.status_code == 403


def test_template_csv_import(app_instance, client):
    org_id, users = _seed_org_users(app_instance)
    with app_instance.app_context():
        tpl = Template(name="CSV Template", engine_type="CSV", organization_id=org_id)
        db.session.add(tpl)
        db.session.commit()
        template_id = tpl.id

    _login(client, users[RoleEnum.ADMIN.value])
    csv_data = "Section,Pos,Part No,Name,Qty\nA,1,P1,Part 1,1\n"
    res = client.post(
        f"/admin/templates/{template_id}/wizard?step=1",
        data={
            "action": "wizard_import_csv",
            "replace_existing": "on",
            "file": (io.BytesIO(csv_data.encode("utf-8")), "parts.csv"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    with app_instance.app_context():
        count = TemplateItem.query.filter_by(template_id=template_id).count()
        assert count == 1


@pytest.mark.skipif(os.environ.get("PILOT_REQUIRE_PDF") != "1", reason="PDF import not required")
def test_template_pdf_import(app_instance, client, tmp_path):
    pdf_path = os.environ.get("PILOT_PDF_SAMPLE")
    if not pdf_path or not os.path.exists(pdf_path):
        pytest.skip("PILOT_PDF_SAMPLE not set or missing")
    org_id, users = _seed_org_users(app_instance)
    with app_instance.app_context():
        tpl = Template(name="PDF Template", engine_type="PDF", organization_id=org_id)
        db.session.add(tpl)
        db.session.commit()
        template_id = tpl.id

    _login(client, users[RoleEnum.ADMIN.value])
    with open(pdf_path, "rb") as f:
        res = client.post(
            f"/admin/templates/{template_id}/wizard?step=1",
            data={
                "action": "wizard_import_pdf",
                "pdf_profile": os.environ.get("PILOT_PDF_PROFILE", "auto"),
                "pdf_file": (io.BytesIO(f.read()), os.path.basename(pdf_path)),
            },
            content_type="multipart/form-data",
        )
    assert res.status_code == 302
    with app_instance.app_context():
        count = TemplateItem.query.filter_by(template_id=template_id).count()
        assert count > 0


def test_job_lifecycle_and_bom_idempotency(app_instance):
    with app_instance.app_context():
        org = Organization(name="Org2", slug="org2")
        db.session.add(org)
        db.session.flush()
        admin = User(
            username="admin2@example.com",
            password_hash=generate_password_hash("Password123!"),
            role=RoleEnum.ADMIN,
            organization_id=org.id,
        )
        db.session.add(admin)
        tpl = Template(name="TPL", engine_type="T", organization_id=org.id)
        db.session.add(tpl)
        db.session.flush()
        db.session.add_all([
            TemplateItem(template_id=tpl.id, organization_id=org.id, section="A", pos=1, part_no="P1", name="Part1", qty=1),
            TemplateItem(template_id=tpl.id, organization_id=org.id, section="A", pos=2, part_no="P2", name="Part2", qty=2),
        ])
        job = Job(
            organization_id=org.id,
            job_pack_id="JP1",
            job_number="JN1",
            template_id=tpl.id,
            created_by_id=admin.id,
        )
        db.session.add(job)
        db.session.commit()

        ensure_survey_from_template(job)
        items = SurveyItem.query.filter_by(job_id=job.id).all()
        for item in items:
            item.decision = DecisionEnum.REPLACE
        db.session.commit()

        created_first = regenerate_bom_for_job(job, items, {})
        created_second = regenerate_bom_for_job(job, items, {})
        count = PartRequirement.query.filter_by(job_id=job.id).count()

        assert created_first == created_second
        assert count == created_first

        change_job_status(job, JobStatusEnum.OFFICE, user=admin)
        assert job.status.name.lower() == "office"


def test_upload_safety(app_instance, client, tmp_path):
    org_id, users = _seed_org_users(app_instance)
    with app_instance.app_context():
        tpl = Template(name="TUP", engine_type="T", organization_id=org_id)
        db.session.add(tpl)
        db.session.commit()
        job = Job(
            organization_id=org_id,
            job_pack_id="JP2",
            job_number="JN2",
            template_id=tpl.id,
            created_by_id=users[RoleEnum.ADMIN.value],
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    _login(client, users[RoleEnum.ADMIN.value])
    res = client.get("/uploads/../secret.txt")
    assert res.status_code == 403

    bad_file = io.BytesIO(b"bad")
    res = client.post(
        f"/jobs/{job_id}/attachments",
        data={"file": (bad_file, "malware.exe", "application/octet-stream")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    good_file = io.BytesIO(b"hello")
    res = client.post(
        f"/jobs/{job_id}/attachments",
        data={"file": (good_file, "note.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302
    good_file2 = io.BytesIO(b"hello")
    res = client.post(
        f"/jobs/{job_id}/attachments",
        data={"file": (good_file2, "note.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302
    with app_instance.app_context():
        count = Attachment.query.filter_by(job_id=job_id).count()
        assert count == 1


def test_upload_integrityerror_not_swallowed(app_instance, client, monkeypatch):
    org_id, users = _seed_org_users(app_instance)
    with app_instance.app_context():
        tpl = Template(name="TUP2", engine_type="T", organization_id=org_id)
        db.session.add(tpl)
        db.session.commit()
        job = Job(
            organization_id=org_id,
            job_pack_id="JP3",
            job_number="JN3",
            template_id=tpl.id,
            created_by_id=users[RoleEnum.ADMIN.value],
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

    _login(client, users[RoleEnum.ADMIN.value])

    def bad_commit():
        dummy = Exception("boom")
        dummy.diag = types.SimpleNamespace(constraint_name="other_constraint")
        raise IntegrityError("stmt", "params", dummy)

    monkeypatch.setattr(db.session, "commit", bad_commit)

    with pytest.raises(IntegrityError):
        client.post(
            f"/jobs/{job_id}/attachments",
            data={"file": (io.BytesIO(b"hello"), "note.txt", "text/plain")},
            content_type="multipart/form-data",
        )


def test_health_ready(app_instance, client):
    res = client.get("/health")
    assert res.status_code == 200
    res = client.get("/ready")
    assert res.status_code == 200


@pytest.mark.skipif(os.environ.get("PILOT_REQUIRE_PDF") != "1", reason="PDF export not required")
def test_pdf_export_smoke(app_instance, client, tmp_path):
    html = "<html><body><h1>Test</h1></body></html>"
    css_path = tmp_path / "report.css"
    css_path.write_text("", encoding="utf-8")
    pdf_bytes = render_report_pdf(html, "http://localhost", str(css_path))
    assert pdf_bytes and len(pdf_bytes) > 100
