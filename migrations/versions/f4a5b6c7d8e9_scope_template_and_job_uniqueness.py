"""Replace legacy global template/job keys with the existing tenant rules.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8

All data checks precede DDL. No rows are modified, merged or deleted. Existing
equivalent unique indexes/constraints are retained, independent of their names.
"""

from alembic import op
import sqlalchemy as sa


revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

RULES = (
    ("templates", (("uq_templates_org_name", ("organization_id", "name")),)),
    ("jobs", (
        ("uq_jobs_org_job_number", ("organization_id", "job_number")),
        ("uq_jobs_org_job_pack_id", ("organization_id", "job_pack_id")),
    )),
)


def _ordinary_key(rule):
    # Frozen reflection policy: do not import evolving application/checker code.
    columns = rule.get("column_names", [])
    if (not columns or not all(isinstance(column, str) for column in columns)
            or rule.get("expressions")
            or any(key.endswith("_where") and value is not None
                   for key, value in rule.get("dialect_options", {}).items())):
        return None
    return frozenset(columns)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        invalid = bind.execute(sa.text("""
            SELECT COUNT(*) FROM pg_catalog.pg_index x
            JOIN pg_catalog.pg_class t ON t.oid = x.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public' AND t.relname IN ('templates', 'jobs')
              AND x.indisunique
              AND (NOT x.indisvalid OR NOT x.indisready OR NOT x.indislive)
        """)).scalar_one()
        if invalid:
            raise RuntimeError("Invalid template/job unique indexes require manual review before migration")

    inspector = sa.inspect(bind)
    plans = []
    for table, wanted in RULES:
        constraints = inspector.get_unique_constraints(table)
        indexes = [index for index in inspector.get_indexes(table) if index["unique"]]
        actual = {_ordinary_key(rule) for rule in [*constraints, *indexes]}
        additions = [(name, columns) for name, columns in wanted if frozenset(columns) not in actual]
        for name, _ in additions:
            if any(rule["name"] == name for rule in [*constraints, *indexes]):
                raise RuntimeError(f"Unique object name {table}.{name} has another definition; manual schema review required")
        legacy_keys = {frozenset(columns) - {"organization_id"} for _, columns in wanted}
        old_constraints = [rule for rule in constraints if _ordinary_key(rule) in legacy_keys]
        old_indexes = [rule for rule in indexes if not rule.get("duplicates_constraint")
                       and _ordinary_key(rule) in legacy_keys]
        # Check all intended keys before changing either table. Do not log key
        # values: diagnostics identify the rule and duplicate-group count only.
        for _, columns in wanted:
            names = ", ".join(columns)  # Frozen identifiers, never user input.
            nulls = " OR ".join(f"{column} IS NULL" for column in columns)
            if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE {nulls}")).scalar_one():
                raise RuntimeError(f"NULL required key in {table}({names}); manual data review required")
            duplicates = bind.execute(sa.text(
                f"SELECT COUNT(*) FROM (SELECT {names} FROM {table} "
                f"GROUP BY {names} HAVING COUNT(*) > 1) AS duplicate_groups"
            )).scalar_one()
            if duplicates:
                raise RuntimeError(
                    f"Cannot enforce uniqueness on {table}({names}): "
                    f"{duplicates} duplicate group(s); manual data review required"
                )
        if additions or old_constraints or old_indexes:
            plans.append((table, additions, old_constraints, old_indexes))

    removed = {(table, _ordinary_key(rule)) for table, _, constraints, indexes in plans
               for rule in [*constraints, *indexes]}
    if removed:
        # Natural-key references in a custom/legacy schema must be redesigned
        # explicitly before removing their global parent key, on either backend.
        for source in inspector.get_table_names():
            for foreign_key in inspector.get_foreign_keys(source):
                target = (foreign_key["referred_table"], frozenset(foreign_key["referred_columns"]))
                if foreign_key.get("referred_schema") in (None, "public") and target in removed:
                    raise RuntimeError(
                        f"Legacy foreign key from {source} references a global {target[0]} key; manual schema review required"
                    )

    if (bind.dialect.name == "sqlite" and plans
            and bind.execute(sa.text("PRAGMA foreign_keys")).scalar_one()):
        raise RuntimeError(
            "SQLite parent-table rebuild with foreign_keys enabled is unsafe; manual migration review required"
        )
    for table, additions, old_constraints, old_indexes in plans:
        # This convention makes SQLite's unnamed legacy UNIQUE constraints
        # addressable during reflection. Existing explicit names are preserved.
        with op.batch_alter_table(table, naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
            for name, columns in additions:
                batch.create_unique_constraint(name, list(columns))
            for rule in old_constraints:
                name = rule["name"] or f"uq_{table}_{rule['column_names'][0]}"
                batch.drop_constraint(name, type_="unique")
            for rule in old_indexes:
                batch.drop_index(rule["name"])


def downgrade():
    raise RuntimeError(
        "Automatic downgrade cannot restore global uniqueness after tenant-scoped values; manual review required"
    )
