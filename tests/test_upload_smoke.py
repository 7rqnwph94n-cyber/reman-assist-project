import base64
import io

import pytest

from models import db, Template, TemplateItem, Job, User, RoleEnum, JobStatusEnum, Organization


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
)


@pytest.fixture
def app_instance(test_app_factory):
    app = test_app_factory(database_uri="sqlite:///:memory:")
    with app.app_context():
        db.session.add(Organization(name="Upload Org", slug="upload-org"))
        db.session.commit()
        yield app


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def create_admin_user():
    org = Organization.query.filter_by(slug="upload-org").first()
    user = User(username="admin", password_hash="x", role=RoleEnum.ADMIN, organization_id=org.id)
    db.session.add(user)
    db.session.commit()
    return user


def test_presurvey_photo_upload_allows_image(app_instance, client):
    with app_instance.app_context():
        user = create_admin_user()
        org = Organization.query.filter_by(slug="upload-org").first()
        tpl = Template(
            name="Upload Template",
            engine_type="U",
            organization_id=org.id,
            pre_survey_schema='[{"label":"Arrived","type":"checkbox","options":""}]',
        )
        db.session.add(tpl)
        db.session.commit()
        job = Job(
            job_number="UP-PS-1",
            job_pack_id="UP-PS-1",
            status=JobStatusEnum.PRE_SURVEY,
            organization_id=org.id,
            template_id=tpl.id,
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp = client.post(
        f"/jobs/{job_id}/pre_survey",
        data={
            "field_1": "on",
            "notes": "ok",
            "photo": (io.BytesIO(PNG_1X1), "photo.png", "image/png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_attachment_upload_allows_pdf(app_instance, client):
    with app_instance.app_context():
        user = create_admin_user()
        org = Organization.query.filter_by(slug="upload-org").first()
        job = Job(
            job_number="UP-ATT-1",
            job_pack_id="UP-ATT-1",
            status=JobStatusEnum.SURVEY,
            organization_id=org.id,
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp = client.post(
        f"/jobs/{job_id}/attachments",
        data={
            "file": (io.BytesIO(b"%PDF-1.4\n%EOF\n"), "test.pdf", "application/pdf")
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_template_import_allows_csv(app_instance, client):
    with app_instance.app_context():
        user = create_admin_user()
        org = Organization.query.filter_by(slug="upload-org").first()
        tpl = Template(name="CSV Template", engine_type="CSV", organization_id=org.id)
        db.session.add(tpl)
        db.session.commit()
        template_id = tpl.id
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    csv_data = "Section,Pos,Part No,Name,Qty\nA,1,PN-1,Part 1,1\n"
    resp = client.post(
        f"/admin/templates/{template_id}/edit",
        data={
            "action": "import_sheet",
            "file": (io.BytesIO(csv_data.encode("utf-8")), "parts.csv", "text/csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app_instance.app_context():
        # Legacy edit route currently validates upload and redirects;
        # detailed CSV import behavior is covered in wizard/import tests.
        Template.query.filter_by(id=template_id).first_or_404()


def test_costing_template_upload_allows_xlsx(app_instance, client):
    with app_instance.app_context():
        user = create_admin_user()
        org = Organization.query.filter_by(slug="upload-org").first()
        tpl = Template(name="Costing Template", engine_type="COST", organization_id=org.id)
        db.session.add(tpl)
        db.session.commit()
        template_id = tpl.id
        user_id = user.id

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    resp = client.post(
        f"/admin/templates/{template_id}/costing/upload",
        data={
            "costing_name": "Costing v1",
            "costing_file": (
                io.BytesIO(b"PK\x03\x04"),
                "costing.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
