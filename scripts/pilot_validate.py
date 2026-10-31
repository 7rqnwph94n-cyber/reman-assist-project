import sys
from sqlalchemy import inspect, text

from app import app as flask_app
from models import db


def main() -> int:
    errors = []

    with flask_app.app_context():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception as exc:
            errors.append(f"DB connection failed: {exc}")

        insp = inspect(db.engine)
        required_tables = [
            "jobs",
            "survey_items",
            "part_requirements",
            "attachments",
            "users",
            "templates",
            "audit_logs",
            "error_logs",
        ]
        for table in required_tables:
            if not insp.has_table(table):
                errors.append(f"Missing table: {table}")

        if insp.has_table("jobs"):
            job_cols = {c["name"] for c in insp.get_columns("jobs")}
            for col in ("survey_version", "parts_version", "template_version"):
                if col not in job_cols:
                    errors.append(f"Missing column jobs.{col}")
        if insp.has_table("templates"):
            template_cols = {c["name"] for c in insp.get_columns("templates")}
            if "version" not in template_cols:
                errors.append("Missing column templates.version")

        try:
            version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception as exc:
            errors.append(f"Could not read alembic_version: {exc}")
            version = None

    if errors:
        print("Pilot validation failed:")
        for e in errors:
            print(f"- {e}")
        if version:
            print(f"Alembic version: {version}")
        return 1

    print("Pilot validation OK")
    if version:
        print(f"Alembic version: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
