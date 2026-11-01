import sys

from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import text

from models import db
from scripts.migration_check import check_database, check_graph, main, migration_script


def test_heads_only_does_not_import_application(monkeypatch):
    # Importing app here would fail; graph validation must be database-free.
    monkeypatch.setitem(sys.modules, "app", None)
    assert main(["--heads-only"]) == 0


def test_graph_rejects_multiple_heads(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    for revision in ("branch_a", "branch_b"):
        (versions / f"{revision}.py").write_text(
            f"revision = '{revision}'\ndown_revision = None\n"
        )
    with pytest.raises(RuntimeError, match="exactly one head"):
        check_graph(ScriptDirectory(str(tmp_path)))


@pytest.mark.parametrize("revision", [None, "cb31edff9cc9", "head"])
def test_database_alignment_requires_actual_head(test_app_factory, revision):
    app = test_app_factory(database_uri="sqlite:///:memory:")
    script = migration_script()
    with app.app_context():
        if revision is not None:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
                ))
                connection.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                    {"revision": script.get_current_head() if revision == "head" else revision},
                )
        if revision == "head":
            check_database(db.engine, script)
        else:
            # A model-created schema or an old revision must not pass CI alignment.
            with pytest.raises(RuntimeError, match="does not match"):
                check_database(db.engine, script)
