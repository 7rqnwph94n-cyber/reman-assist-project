import pytest

from models import db, Template, TemplateItem, RoleEnum, User, TemplateWizardState, TemplatePart, TemplateOccurrence, Organization
from werkzeug.security import generate_password_hash


@pytest.fixture()
def app_instance(tmp_path, test_app_factory):
    app = test_app_factory(database_uri=f"sqlite:///{tmp_path / 'wizard_canon.db'}")
    with app.app_context():
        db.session.add(Organization(name="Canon Org", slug="canon-org"))
        db.session.commit()
        yield app


@pytest.fixture()
def client(app_instance):
    return app_instance.test_client()


def _login_as_admin(client, app_instance):
    with app_instance.app_context():
        org = Organization.query.filter_by(slug="canon-org").first()
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


def test_wizard_builds_canonical(app_instance, client):
    _login_as_admin(client, app_instance)
    with app_instance.app_context():
        org = Organization.query.filter_by(slug="canon-org").first()
        tpl = Template(name="Canon Tpl", engine_type="CAN", organization_id=org.id)
        db.session.add(tpl)
        db.session.flush()
        db.session.add_all(
            [
                TemplateItem(
                    template_id=tpl.id,
                    organization_id=tpl.organization_id,
                    section="A",
                    pos=1,
                    part_no="51.01100-6114",
                    name="Case",
                    qty=1,
                ),
                TemplateItem(
                    template_id=tpl.id,
                    organization_id=tpl.organization_id,
                    section="A",
                    pos=2,
                    part_no="51.90020-0352",
                    name="Bolt",
                    qty=14,
                ),
            ]
        )
        db.session.commit()
        template_id = tpl.id

    res = client.post(
        f"/admin/templates/{template_id}/wizard?step=1",
        data={"action": "wizard_build_canonical"},
    )
    assert res.status_code == 302

    with app_instance.app_context():
        parts = TemplatePart.query.filter_by(template_id=template_id).all()
        occ = TemplateOccurrence.query.filter_by(template_id=template_id).all()
        assert len(parts) == 2
        assert len(occ) == 2
