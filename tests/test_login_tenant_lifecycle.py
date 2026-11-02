"""Real Flask/SQLAlchemy requests on guarded SQLite, not PostgreSQL results."""

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from models import db, Job, JobStatusEnum, Organization, RoleEnum, SurveyItem, Template, User
from postgres_tests import test_workflow as workflow
from tests.db_safety import assert_engine_database
from utils.tenant_scope import get_current_org_id


ROLES = [RoleEnum.ADMIN, RoleEnum.OFFICE, RoleEnum.TECHNICIAN]


@pytest.fixture
def sqlite_workflow(test_app_factory):
    app = test_app_factory()
    with app.app_context():
        assert_engine_database(db.engine, app.config["SQLALCHEMY_DATABASE_URI"])
        users = {}
        for label in ("owner", "other"):
            org = Organization(name=label, slug=label)
            db.session.add(org)
            db.session.flush()
            users[label] = {}
            for role in RoleEnum:
                user = User(username=f"{label}-{role.name}@example.com", role=role,
                            organization_id=org.id, password_hash=generate_password_hash(workflow.PASSWORD))
                db.session.add(user)
                db.session.flush()
                users[label][role] = {"id": user.id, "username": user.username, "org_id": org.id, "role": role}
        owner = users["owner"]
        template = Template(name="Victim template", organization_id=owner[RoleEnum.ADMIN]["org_id"])
        db.session.add(template)
        db.session.flush()
        job = Job(job_number="VICTIM-A", job_pack_id="PACK-A", template_id=template.id,
                  organization_id=owner[RoleEnum.ADMIN]["org_id"], status=JobStatusEnum.PRE_SURVEY,
                  assigned_to_id=owner[RoleEnum.TECHNICIAN]["id"], created_by_id=owner[RoleEnum.OFFICE]["id"])
        db.session.add(job)
        db.session.flush()
        db.session.add(SurveyItem(job_id=job.id, name="Victim survey", qty=1))
        other = users["other"]
        own_job = Job(job_number="OWN-B", job_pack_id="PACK-B", organization_id=other[RoleEnum.ADMIN]["org_id"],
                      assigned_to_id=other[RoleEnum.TECHNICIAN]["id"], created_by_id=other[RoleEnum.OFFICE]["id"])
        db.session.add(own_job)
        db.session.commit()
        data = {"users": users, "job_id": job.id, "template_id": template.id, "other_job_id": own_job.id}
    return app, app.test_client(), data


@pytest.mark.parametrize("role", ROLES)
def test_raw_cross_tenant_relogin_is_rejected_with_original_identity_preserved(sqlite_workflow, role):
    app, client, data = sqlite_workflow
    owner = data["users"]["owner"][RoleEnum.OFFICE]
    outsider = data["users"]["other"][role]
    with app.app_context():
        user = db.session.get(User, outsider["id"])
        assert user.username == outsider["username"] and user.role == role
        assert user.organization_id == outsider["org_id"] != owner["org_id"]
        assert check_password_hash(user.password_hash, workflow.PASSWORD)
    assert client.post("/login", data={"username": owner["username"], "password": workflow.PASSWORD}).status_code == 302
    response = client.post("/login", data={"username": outsider["username"], "password": workflow.PASSWORD})
    assert response.status_code == 200
    assert "Invalid username or password." in response.get_data(as_text=True)
    assert "Too many login attempts" not in response.get_data(as_text=True)
    with client.session_transaction() as session:
        assert session["user_id"] == owner["id"] != outsider["id"]
    assert get_current_org_id() is None
    assert client.get(f"/jobs/{data['job_id']}").status_code == 200


@pytest.mark.parametrize("role", list(RoleEnum))
def test_login_helper_authenticates_the_outsider_after_owner_session(sqlite_workflow, role):
    app, client, data = sqlite_workflow
    workflow.login(client, data["users"]["owner"][RoleEnum.OFFICE])
    outsider = data["users"]["other"][role]
    workflow.login(client, outsider)
    with client.session_transaction() as session:
        assert session["user_id"] == outsider["id"]
    if role == RoleEnum.STORES:
        assert client.get("/stores?view=master").status_code == 200
        assert client.get(f"/jobs/{data['other_job_id']}").status_code == 403
    else:
        assert client.get(f"/jobs/{data['other_job_id']}").status_code == 200


@pytest.mark.parametrize("role", ROLES)
def test_authenticated_tenant_denials_and_authorised_own_job_requests(sqlite_workflow, role):
    app, client, data = sqlite_workflow
    workflow.login(client, data["users"]["owner"][RoleEnum.OFFICE])
    workflow.assert_cross_organisation_isolation(app, client, data, role)


def test_wrong_password_never_creates_an_authenticated_session(sqlite_workflow):
    app, client, data = sqlite_workflow
    outsider = data["users"]["other"][RoleEnum.ADMIN]
    response = client.post("/login", data={"username": outsider["username"], "password": "WrongPassword123!"})
    assert response.status_code == 200
    assert "Invalid username or password." in response.get_data(as_text=True)
    with client.session_transaction() as session:
        assert "user_id" not in session
    response = client.get(f"/jobs/{data['other_job_id']}")
    assert response.status_code == 302 and response.location.endswith("/login")
    workflow.login(client, outsider)
    assert client.get(f"/jobs/{data['other_job_id']}").status_code == 200
