from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import create_engine

import app as app_module
from models import db, Organization
from tests.db_safety import allow_database, assert_engine_database


@pytest.mark.parametrize("database_kind", ["file", "memory"])
def test_fresh_apps_have_independent_engines(test_app_factory, tmp_path, database_kind):
    # A previously configured default app must not determine either test engine.
    default = app_module.create_app()
    default_config = dict(default.config)
    with default.app_context():
        default_engine = db.engine
        assert_engine_database(default_engine, "sqlite:///:memory:")

    uris = (
        [f"sqlite:///{tmp_path / name}" for name in ("first.db", "second.db")]
        if database_kind == "file"
        else ["sqlite:///:memory:"] * 2
    )
    first = test_app_factory(database_uri=uris[0], ENABLE_TEST_SELECTORS=True)
    second = test_app_factory(database_uri=uris[1], ENABLE_TEST_SELECTORS=False)
    assert first is not second and first is not default and second is not default
    with first.app_context():
        first_engine = db.engine
        assert_engine_database(first_engine, uris[0])
        db.session.add(Organization(name="First", slug="same-slug"))
        db.session.commit()
    with second.app_context():
        second_engine = db.engine
        assert_engine_database(second_engine, uris[1])
        assert Organization.query.count() == 0
        db.session.add(Organization(name="Second", slug="same-slug"))
        db.session.commit()
    assert first_engine is not second_engine
    assert first_engine is not default_engine and second_engine is not default_engine
    with first.app_context():
        assert [org.name for org in Organization.query.all()] == ["First"]
    assert dict(default.config) == default_config
    assert app_module.create_app() is default

    # Template globals must read the app currently rendering, not the default.
    for app, expected in ((first, 'data-testid="probe"'), (second, "")):
        with app.test_request_context():
            assert app_module.inject_globals()["testid"]("probe") == expected


def test_upload_route_uses_its_own_app(test_app_factory, tmp_path):
    from models import RoleEnum, User

    for number in (1, 2):
        upload_root = tmp_path / f"uploads-{number}"
        app = test_app_factory(
            database_uri=f"sqlite:///{tmp_path / f'upload-{number}.db'}",
            UPLOAD_FOLDER=str(upload_root),
        )
        images = upload_root / "section_images"
        images.mkdir()
        (images / "probe.txt").write_text(f"app-{number}")
        with app.app_context():
            org = Organization(name="Uploads", slug="uploads")
            db.session.add(org)
            db.session.flush()
            user = User(
                username="admin", password_hash="unused", role=RoleEnum.ADMIN,
                organization_id=org.id,
            )
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        client = app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user_id
        response = client.get("/uploads/section_images/probe.txt")
        assert response.status_code == 200
        assert response.get_data(as_text=True) == f"app-{number}"
        response.close()


def test_guards_reject_undesignated_connections(test_app_factory, tmp_path):
    test_app_factory()
    # Being next to a designated database does not make another path safe.
    undesignated = tmp_path / "not-designated.db"
    with pytest.raises(RuntimeError, match="non-designated database"):
        sqlite3.connect(undesignated)
    engine = create_engine(f"sqlite:///{undesignated}")
    try:
        with pytest.raises(RuntimeError, match="non-designated database"):
            engine.connect()
    finally:
        engine.dispose()
    assert not undesignated.exists()


def test_guard_refuses_existing_database(tmp_path):
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"existing application data")
    with pytest.raises(RuntimeError, match="existing database"):
        allow_database(existing, tmp_path)
    assert existing.read_bytes() == b"existing application data"


def test_factory_refuses_application_database(test_app_factory):
    application_db = Path(app_module.__file__).parent / "app.db"
    with pytest.raises(RuntimeError, match="temporary directory"):
        test_app_factory(database_uri=f"sqlite:///{application_db}")
