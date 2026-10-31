import pytest
import io

from app import create_app
from services.illustration_helpers import _extract_rows_from_pdf_text
from models import (
    db,
    Template,
    TemplateItem,
    TemplateSection,
    IllustrationPage,
    IllustrationPartRow,
    RoleEnum,
    User,
    TemplateWizardState,
    Organization,
)
from werkzeug.security import generate_password_hash


@pytest.fixture()
def app_instance(tmp_path):
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        ENFORCE_CSRF=False,
    )
    with app.app_context():
        db.create_all()
        db.session.add(Organization(name="Illustration Org", slug="illo-org"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app_instance):
    return app_instance.test_client()


def _login_as_admin(client, app_instance):
    with app_instance.app_context():
        org = Organization.query.filter_by(slug="illo-org").first()
        admin = User(
            username="admin@example.com",
            role=RoleEnum.ADMIN,
            password_hash=generate_password_hash("Password123!"),
            organization_id=org.id,
        )
        db.session.add(admin)
        db.session.commit()
        user_id = admin.id
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _seed_template(app_instance):
    with app_instance.app_context():
        org = Organization.query.filter_by(slug="illo-org").first()
        tpl = Template(name="Illo Template", engine_type="ILL", organization_id=org.id)
        db.session.add(tpl)
        db.session.flush()
        db.session.add(
            TemplateItem(
                template_id=tpl.id,
                organization_id=org.id,
                section="A",
                pos=1,
                part_no="P1",
                name="Part 1",
                qty=1,
            )
        )
        db.session.commit()
        section = TemplateSection(template_id=tpl.id, name="A", display_order=1)
        db.session.add(section)
        page = IllustrationPage(title="Test", image_path="x.png", status="draft")
        db.session.add(page)
        db.session.commit()
        return tpl.id, section.id, page.id


def test_import_parts_validates_duplicate_pos(app_instance, client):
    _login_as_admin(client, app_instance)
    with app_instance.app_context():
        _tpl_id, _section_id, page_id = _seed_template(app_instance)

    res = client.post(
        f"/api/illustrations/{page_id}/parts/import",
        json={"rows": [{"pos": 1}, {"pos": 1}]},
    )
    assert res.status_code == 400


def test_import_parts_creates_rows(app_instance, client):
    _login_as_admin(client, app_instance)
    with app_instance.app_context():
        _tpl_id, _section_id, page_id = _seed_template(app_instance)

    res = client.post(
        f"/api/illustrations/{page_id}/parts/import",
        json={"rows": [{"pos": 1, "part_no": "X", "qty": 2, "designation": "Desc"}]},
    )
    assert res.status_code == 200

    with app_instance.app_context():
        rows = IllustrationPartRow.query.filter_by(illustration_page_id=page_id).all()
        assert len(rows) == 1
        assert rows[0].pos == 1
        assert rows[0].part_no == "X"


def test_pdf_text_extraction_parses_rows():
    text = """POS  Part No  Qty  Description
1  ABC-001  2  GASKET
2  DEF-002  1  BOLT
"""
    rows = _extract_rows_from_pdf_text(text)
    assert rows
    assert rows[0]["pos"] == 1
    assert rows[1]["pos"] == 2


def test_pdf_text_extraction_man_format():
    text = """1
51.01100-6114
1
CRANKCASE ASSEMBLY
2
51.90020-0352
14
HEX COLLAR BOLT M14X118-10.9-PHR
"""
    rows = _extract_rows_from_pdf_text(text)
    assert len(rows) == 2
    assert rows[0]["pos"] == 1
    assert rows[0]["part_no"] == "51.01100-6114"
    assert rows[0]["qty"] == 1
    assert rows[1]["pos"] == 2
    assert rows[1]["qty"] == 14


def test_wizard_csv_import_updates_state(tmp_path):
    app = create_app()
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'wizard.db'}",
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        ENFORCE_CSRF=False,
    )
    with app.app_context():
        db.create_all()
        db.session.add(Organization(name="Wizard Org", slug="wizard-org"))
        db.session.commit()
        org = Organization.query.filter_by(slug="wizard-org").first()
        admin = User(
            username="admin@example.com",
            role=RoleEnum.ADMIN,
            password_hash=generate_password_hash("Password123!"),
            organization_id=org.id,
        )
        template = Template(name="Wizard Template", engine_type="WIZ", organization_id=org.id)
        db.session.add_all([admin, template])
        db.session.commit()
        user_id = admin.id
        template_id = template.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

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

    with app.app_context():
        wizard = TemplateWizardState.query.filter_by(template_id=template_id).first()
        assert wizard is not None
        assert wizard.step_status and wizard.step_status.get("step1", {}).get("complete") is True
