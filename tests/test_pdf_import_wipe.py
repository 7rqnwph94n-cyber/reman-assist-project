import io
import os
import sys
import types
import pytest

from models import (
    db,
    Organization,
    User,
    RoleEnum,
    Template,
    TemplateItem,
    TemplateSection,
    IllustrationPage,
    TemplateSectionIllustrationLink,
)
from werkzeug.security import generate_password_hash


@pytest.fixture()
def app_instance(tmp_path, test_app_factory):
    app = test_app_factory(database_uri=f"sqlite:///{tmp_path / 'wipe.db'}")
    with app.app_context():
        yield app


@pytest.fixture()
def client(app_instance):
    return app_instance.test_client()


def _seed(app_instance):
    with app_instance.app_context():
        org = Organization(name="Org", slug="org")
        db.session.add(org)
        db.session.flush()
        admin = User(
            username="admin@example.com",
            password_hash=generate_password_hash("Password123!"),
            role=RoleEnum.ADMIN,
            organization_id=org.id,
        )
        db.session.add(admin)
        tpl = Template(name="T", engine_type="E", organization_id=org.id)
        db.session.add(tpl)
        db.session.flush()
        item = TemplateItem(template_id=tpl.id, organization_id=org.id, section="A", pos=1, part_no="P1", name="Part1", qty=1)
        db.session.add(item)
        sec = TemplateSection(template_id=tpl.id, name="A", display_order=1)
        db.session.add(sec)
        page = IllustrationPage(title="P", image_path="x.png", status="draft")
        db.session.add(page)
        db.session.flush()
        link = TemplateSectionIllustrationLink(template_section_id=sec.id, illustration_page_id=page.id, display_order=1)
        db.session.add(link)
        db.session.commit()
        return admin.id, tpl.id


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_pdf_import_missing_extractor_does_not_wipe(app_instance, client):
    admin_id, template_id = _seed(app_instance)
    _login(client, admin_id)

    res = client.post(
        f"/admin/templates/{template_id}/wizard?step=1",
        data={
            "action": "wizard_import_pdf",
            "pdf_profile": "auto",
            "confirm_wipe": "1",
            "wipe_confirm_text": "WIPE",
            "pdf_file": (io.BytesIO(b"%PDF-1.4"), "test.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    with app_instance.app_context():
        assert TemplateItem.query.filter_by(template_id=template_id).count() == 1
        assert IllustrationPage.query.count() == 1


def test_pdf_import_failure_rolls_back(app_instance, client, monkeypatch):
    admin_id, template_id = _seed(app_instance)
    _login(client, admin_id)

    fake_pkg = types.ModuleType("pdf_parts_extractor")
    fake_extract = types.ModuleType("pdf_parts_extractor.extract")
    fake_profiles = types.ModuleType("pdf_parts_extractor.profiles")

    def run_extract(_pdf, _out, _profile, debug=False):
        raise RuntimeError("boom")

    def list_profiles():
        return ["man.json"]

    fake_extract.run_extract = run_extract
    fake_profiles.list_profiles = list_profiles

    monkeypatch.setitem(sys.modules, "pdf_parts_extractor", fake_pkg)
    monkeypatch.setitem(sys.modules, "pdf_parts_extractor.extract", fake_extract)
    monkeypatch.setitem(sys.modules, "pdf_parts_extractor.profiles", fake_profiles)

    res = client.post(
        f"/admin/templates/{template_id}/wizard?step=1",
        data={
            "action": "wizard_import_pdf",
            "pdf_profile": "man.json",
            "confirm_wipe": "1",
            "wipe_confirm_text": "WIPE",
            "pdf_file": (io.BytesIO(b"%PDF-1.4"), "test.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    with app_instance.app_context():
        assert TemplateItem.query.filter_by(template_id=template_id).count() == 1
        assert IllustrationPage.query.count() == 1


def test_pdf_import_failure_cleans_files(app_instance, client, monkeypatch, tmp_path):
    admin_id, template_id = _seed(app_instance)
    _login(client, admin_id)

    fake_pkg = types.ModuleType("pdf_parts_extractor")
    fake_extract = types.ModuleType("pdf_parts_extractor.extract")
    fake_profiles = types.ModuleType("pdf_parts_extractor.profiles")

    def run_extract(_pdf, out_dir, _profile, debug=False):
        os.makedirs(os.path.join(out_dir, "images", "x"), exist_ok=True)
        with open(os.path.join(out_dir, "parts.csv"), "w", encoding="utf-8") as f:
            f.write("group_id,part_no,description,qty\\nTA0100,P1,Part,1\\n")
        with open(os.path.join(out_dir, "images", "x", "TA0100_diagram_p1.jpg"), "wb") as f:
            f.write(b"img")

    def list_profiles():
        return ["man.json"]

    fake_extract.run_extract = run_extract
    fake_profiles.list_profiles = list_profiles

    monkeypatch.setitem(sys.modules, "pdf_parts_extractor", fake_pkg)
    monkeypatch.setitem(sys.modules, "pdf_parts_extractor.extract", fake_extract)
    monkeypatch.setitem(sys.modules, "pdf_parts_extractor.profiles", fake_profiles)

    def bad_copy(src, dst, *, _orig=__import__("shutil").copyfile):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(b"partial")
        raise RuntimeError("copy failed")

    monkeypatch.setattr("shutil.copyfile", bad_copy)

    res = client.post(
        f"/admin/templates/{template_id}/wizard?step=1",
        data={
            "action": "wizard_import_pdf",
            "pdf_profile": "man.json",
            "confirm_wipe": "1",
            "wipe_confirm_text": "WIPE",
            "pdf_file": (io.BytesIO(b"%PDF-1.4"), "test.pdf", "application/pdf"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 302

    uploads = (tmp_path / "uploads").glob("**/*")
    assert not any(p.is_file() for p in uploads)
