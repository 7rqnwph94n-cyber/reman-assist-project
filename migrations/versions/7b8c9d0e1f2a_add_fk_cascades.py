"""add_fk_cascades

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2025-01-18 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7b8c9d0e1f2a"
down_revision = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


def _with_fk(batch_op, name: str, source_cols, target_table: str, target_cols, ondelete: str | None = None):
    batch_op.drop_constraint(name, type_="foreignkey")
    batch_op.create_foreign_key(name, target_table, source_cols, target_cols, ondelete=ondelete)


def _costing_upload_fk_name(bind):
    # 4d5e6f7a8b9c named this FK explicitly; model-created databases used the
    # PostgreSQL default name. Preserve whichever matching constraint exists.
    matches = [fk["name"] for fk in sa.inspect(bind).get_foreign_keys("costing_sheets")
               if fk["constrained_columns"] == ["job_costing_upload_id"]
               and fk["referred_table"] == "job_costing_uploads"
               and fk["referred_columns"] == ["id"]]
    if len(matches) != 1 or not matches[0]:
        raise RuntimeError("Expected exactly one named costing_sheets job_costing_upload_id foreign key")
    return matches[0]


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    with op.batch_alter_table("survey_items", schema=None) as batch_op:
        _with_fk(batch_op, "survey_items_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("part_requirements", schema=None) as batch_op:
        _with_fk(batch_op, "part_requirements_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")
        _with_fk(batch_op, "part_requirements_survey_item_id_fkey", ["survey_item_id"], "survey_items", ["id"], ondelete="SET NULL")

    with op.batch_alter_table("attachments", schema=None) as batch_op:
        _with_fk(batch_op, "attachments_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("template_items", schema=None) as batch_op:
        _with_fk(batch_op, "template_items_template_id_fkey", ["template_id"], "templates", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("template_groups", schema=None) as batch_op:
        _with_fk(batch_op, "template_groups_template_id_fkey", ["template_id"], "templates", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("template_item_groups", schema=None) as batch_op:
        _with_fk(batch_op, "template_item_groups_template_item_id_fkey", ["template_item_id"], "template_items", ["id"], ondelete="CASCADE")
        _with_fk(batch_op, "template_item_groups_template_group_id_fkey", ["template_group_id"], "template_groups", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("store_items", schema=None) as batch_op:
        _with_fk(batch_op, "store_items_template_item_id_fkey", ["template_item_id"], "template_items", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("pick_lists", schema=None) as batch_op:
        _with_fk(batch_op, "pick_lists_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("pick_list_items", schema=None) as batch_op:
        _with_fk(batch_op, "pick_list_items_pick_list_id_fkey", ["pick_list_id"], "pick_lists", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        _with_fk(batch_op, "audit_logs_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    # No predecessor creates this table. Legacy/model-created databases may
    # already have it; fresh databases receive it in d2e3f4a5b6c7 with CASCADE.
    if sa.inspect(bind).has_table("job_report_revisions"):
        with op.batch_alter_table("job_report_revisions", schema=None) as batch_op:
            _with_fk(batch_op, "job_report_revisions_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("job_logs", schema=None) as batch_op:
        _with_fk(batch_op, "job_logs_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("pre_survey_results", schema=None) as batch_op:
        _with_fk(batch_op, "pre_survey_results_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("epicor_settings", schema=None) as batch_op:
        _with_fk(batch_op, "epicor_settings_template_id_fkey", ["template_id"], "templates", ["id"], ondelete="SET NULL")

    with op.batch_alter_table("job_costing_uploads", schema=None) as batch_op:
        _with_fk(batch_op, "job_costing_uploads_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("costing_template_profiles", schema=None) as batch_op:
        _with_fk(batch_op, "costing_template_profiles_engine_template_id_fkey", ["engine_template_id"], "templates", ["id"], ondelete="SET NULL")

    with op.batch_alter_table("costing_template_lines", schema=None) as batch_op:
        _with_fk(batch_op, "costing_template_lines_costing_template_profile_id_fkey", ["costing_template_profile_id"], "costing_template_profiles", ["id"], ondelete="CASCADE")

    with op.batch_alter_table("costing_sheets", schema=None) as batch_op:
        _with_fk(batch_op, "costing_sheets_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete="CASCADE")
        _with_fk(batch_op, _costing_upload_fk_name(bind), ["job_costing_upload_id"], "job_costing_uploads", ["id"], ondelete="SET NULL")
        _with_fk(batch_op, "costing_sheets_costing_template_profile_id_fkey", ["costing_template_profile_id"], "costing_template_profiles", ["id"], ondelete="SET NULL")

    with op.batch_alter_table("costing_lines", schema=None) as batch_op:
        _with_fk(batch_op, "costing_lines_costing_sheet_id_fkey", ["costing_sheet_id"], "costing_sheets", ["id"], ondelete="CASCADE")
        _with_fk(batch_op, "costing_lines_part_requirement_id_fkey", ["part_requirement_id"], "part_requirements", ["id"], ondelete="SET NULL")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    with op.batch_alter_table("costing_lines", schema=None) as batch_op:
        _with_fk(batch_op, "costing_lines_costing_sheet_id_fkey", ["costing_sheet_id"], "costing_sheets", ["id"], ondelete=None)
        _with_fk(batch_op, "costing_lines_part_requirement_id_fkey", ["part_requirement_id"], "part_requirements", ["id"], ondelete=None)

    with op.batch_alter_table("costing_sheets", schema=None) as batch_op:
        _with_fk(batch_op, "costing_sheets_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)
        _with_fk(batch_op, _costing_upload_fk_name(bind), ["job_costing_upload_id"], "job_costing_uploads", ["id"], ondelete=None)
        _with_fk(batch_op, "costing_sheets_costing_template_profile_id_fkey", ["costing_template_profile_id"], "costing_template_profiles", ["id"], ondelete=None)

    with op.batch_alter_table("costing_template_lines", schema=None) as batch_op:
        _with_fk(batch_op, "costing_template_lines_costing_template_profile_id_fkey", ["costing_template_profile_id"], "costing_template_profiles", ["id"], ondelete=None)

    with op.batch_alter_table("costing_template_profiles", schema=None) as batch_op:
        _with_fk(batch_op, "costing_template_profiles_engine_template_id_fkey", ["engine_template_id"], "templates", ["id"], ondelete=None)

    with op.batch_alter_table("job_costing_uploads", schema=None) as batch_op:
        _with_fk(batch_op, "job_costing_uploads_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    with op.batch_alter_table("epicor_settings", schema=None) as batch_op:
        _with_fk(batch_op, "epicor_settings_template_id_fkey", ["template_id"], "templates", ["id"], ondelete=None)

    with op.batch_alter_table("pre_survey_results", schema=None) as batch_op:
        _with_fk(batch_op, "pre_survey_results_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    with op.batch_alter_table("job_logs", schema=None) as batch_op:
        _with_fk(batch_op, "job_logs_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    if sa.inspect(bind).has_table("job_report_revisions"):
        with op.batch_alter_table("job_report_revisions", schema=None) as batch_op:
            _with_fk(batch_op, "job_report_revisions_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        _with_fk(batch_op, "audit_logs_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    with op.batch_alter_table("pick_list_items", schema=None) as batch_op:
        _with_fk(batch_op, "pick_list_items_pick_list_id_fkey", ["pick_list_id"], "pick_lists", ["id"], ondelete=None)

    with op.batch_alter_table("pick_lists", schema=None) as batch_op:
        _with_fk(batch_op, "pick_lists_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    with op.batch_alter_table("store_items", schema=None) as batch_op:
        _with_fk(batch_op, "store_items_template_item_id_fkey", ["template_item_id"], "template_items", ["id"], ondelete=None)

    with op.batch_alter_table("template_item_groups", schema=None) as batch_op:
        _with_fk(batch_op, "template_item_groups_template_item_id_fkey", ["template_item_id"], "template_items", ["id"], ondelete=None)
        _with_fk(batch_op, "template_item_groups_template_group_id_fkey", ["template_group_id"], "template_groups", ["id"], ondelete=None)

    with op.batch_alter_table("template_groups", schema=None) as batch_op:
        _with_fk(batch_op, "template_groups_template_id_fkey", ["template_id"], "templates", ["id"], ondelete=None)

    with op.batch_alter_table("template_items", schema=None) as batch_op:
        _with_fk(batch_op, "template_items_template_id_fkey", ["template_id"], "templates", ["id"], ondelete=None)

    with op.batch_alter_table("attachments", schema=None) as batch_op:
        _with_fk(batch_op, "attachments_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)

    with op.batch_alter_table("part_requirements", schema=None) as batch_op:
        _with_fk(batch_op, "part_requirements_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)
        _with_fk(batch_op, "part_requirements_survey_item_id_fkey", ["survey_item_id"], "survey_items", ["id"], ondelete=None)

    with op.batch_alter_table("survey_items", schema=None) as batch_op:
        _with_fk(batch_op, "survey_items_job_id_fkey", ["job_id"], "jobs", ["id"], ondelete=None)
