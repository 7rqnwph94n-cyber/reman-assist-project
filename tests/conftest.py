import os
import sys
from pathlib import Path

# Set DYLD_LIBRARY_PATH before any native-lib import (WeasyPrint / cffi).
if sys.platform == "darwin":
    _existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    for _candidate in ["/opt/homebrew/lib", "/usr/local/lib"]:
        if _candidate not in _existing:
            _existing = f"{_existing}:{_candidate}" if _existing else _candidate
    os.environ["DYLD_LIBRARY_PATH"] = _existing

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from models import (
    db,
    User,
    RoleEnum,
    Organization,
    Job,
    Template,
    TemplateItem,
    TemplateSection,
    JobStatusEnum,
    PartRequirement,
    PickList,
    PickListItem,
)
from services.seed_data import seed_database

DEFAULT_TEST_ORG_SLUG = "global-reman"


def _detect_pdf_renderer() -> str:
    """Return the best available PDF engine name."""
    try:
        import weasyprint  # type: ignore  # noqa: F401
        return "weasyprint"
    except Exception:
        pass
    try:
        import playwright.sync_api  # type: ignore  # noqa: F401
        return "playwright"
    except Exception:
        pass
    return "stub"


def _get_default_org():
    return Organization.query.filter_by(slug=DEFAULT_TEST_ORG_SLUG).first()


@pytest.fixture
def app_for_tests(tmp_path: Path):
    from app import app as flask_app
    flask_app._configured = False
    flask_app._got_first_request = False
    app = create_app()
    pdf_engine = _detect_pdf_renderer()
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        ENFORCE_CSRF=False,
        ENABLE_LEGACY_EXPORT=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
        PDF_RENDERER=pdf_engine,
        PDF_RENDERER_FALLBACK="stub",
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
        default_org = Organization(name="Global Reman", slug=DEFAULT_TEST_ORG_SLUG)
        db.session.add(default_org)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app_for_tests):
    return app_for_tests.test_client()


@pytest.fixture
def seed_basic(app_for_tests):
    with app_for_tests.app_context():
        seed_database(
            users=4,
            templates=1,
            jobs=2,
            items_per_template=6,
            bom_lines_per_job=6,
            with_attachments=False,
            upload_folder=app_for_tests.config.get("UPLOAD_FOLDER"),
        )


def _create_user(username: str, role: RoleEnum):
    org = _get_default_org()
    user = User(
        username=username,
        role=role,
        password_hash=generate_password_hash("Password123!"),
        organization_id=org.id if org else None,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def seed_users(app_for_tests):
    with app_for_tests.app_context():
        _create_user("admin@example.com", RoleEnum.ADMIN)
        _create_user("office@example.com", RoleEnum.OFFICE)
        _create_user("tech@example.com", RoleEnum.TECHNICIAN)
        _create_user("stores@example.com", RoleEnum.STORES)
        return [
            "admin@example.com",
            "office@example.com",
            "tech@example.com",
            "stores@example.com",
        ]


@pytest.fixture
def job_id(app_for_tests, seed_users):
    with app_for_tests.app_context():
        org = _get_default_org()
        tech_user = User.query.filter_by(username="tech@example.com").first()
        office_user = User.query.filter_by(username="office@example.com").first()
        template = Template(name="RBAC Template", engine_type="RBAC", organization_id=org.id if org else None)
        db.session.add(template)
        db.session.flush()
        section = TemplateSection(template_id=template.id, name="A", display_order=1)
        db.session.add(section)
        db.session.flush()
        for i in range(1, 4):
            db.session.add(
                TemplateItem(
                    template_id=template.id,
                    organization_id=org.id if org else None,
                    section="A",
                    pos=i,
                    part_no=f"RB-{i:03d}",
                    name=f"RBAC Part {i}",
                    qty=1,
                )
            )
        job = Job(
            job_number="RBAC-001",
            job_pack_id="RBAC-001",
            status=JobStatusEnum.SURVEY,
            template_id=template.id,
            organization_id=org.id if org else None,
            assigned_to_id=tech_user.id if tech_user else None,
            created_by_id=office_user.id if office_user else None,
        )
        db.session.add(job)
        db.session.commit()
        return job.id


@pytest.fixture
def rbac_ids(app_for_tests, seed_users):
    with app_for_tests.app_context():
        org = _get_default_org()
        admin = User.query.filter_by(username="admin@example.com").first()
        office = User.query.filter_by(username="office@example.com").first()
        tech = User.query.filter_by(username="tech@example.com").first()

        template = Template(name="RBAC Template", engine_type="RBAC", organization_id=org.id if org else None)
        db.session.add(template)
        db.session.flush()
        section = TemplateSection(template_id=template.id, name="A", display_order=1)
        db.session.add(section)
        db.session.flush()
        t_item = TemplateItem(
            template_id=template.id,
            organization_id=org.id if org else None,
            section="A",
            pos=1,
            part_no="RB-001",
            name="RBAC Item",
            qty=1,
        )
        db.session.add(t_item)
        db.session.flush()

        job = Job(
            job_number="RBAC-EXT-001",
            job_pack_id="RBAC-EXT-001",
            status=JobStatusEnum.SURVEY,
            template_id=template.id,
            organization_id=org.id if org else None,
            assigned_to_id=tech.id if tech else None,
            created_by_id=office.id if office else None,
        )
        db.session.add(job)
        db.session.flush()

        part = PartRequirement(
            job_id=job.id,
            part_no="RB-PART-001",
            name="RBAC Part",
            qty_required=1,
        )
        db.session.add(part)

        picklist = PickList(
            job_id=job.id,
            organization_id=org.id if org else None,
            created_by_id=admin.id if admin else None,
        )
        db.session.add(picklist)
        db.session.flush()
        db.session.add(
            PickListItem(
                pick_list_id=picklist.id,
                organization_id=org.id if org else None,
                part_no="RB-PART-001",
                name="RBAC Part",
                qty_required=1,
                stock_at_issue=0,
            )
        )

        delete_target = User(
            username="delete_target@example.com",
            role=RoleEnum.TECHNICIAN,
            password_hash=generate_password_hash("Password123!"),
            organization_id=org.id if org else None,
        )
        db.session.add(delete_target)
        db.session.commit()

        return {
            "job_id": job.id,
            "template_id": template.id,
            "section_id": section.id,
            "picklist_id": picklist.id,
            "page_id": 1,
            "label_id": 1,
            "upload_id": 1,
            "user_id": delete_target.id,
            "filename": "missing.txt",
        }


def login_as(client, username="admin@example.com", password="Password123!"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
