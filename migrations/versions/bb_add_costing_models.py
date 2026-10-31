"""add costing sheet and template models

Revision ID: bb_add_costing_models
Revises: aa_add_part_approval
Create Date: 2025-12-07 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "bb_add_costing_models"
down_revision = "aa_add_part_approval"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    EnumType = postgresql.ENUM if is_postgres else sa.Enum

    costing_stage_enum = EnumType(
        "awaiting_sas",
        "costing_in_progress",
        "awaiting_po",
        "engine_in_build",
        "complete",
        name="costingstageenum",
        create_type=False,
    )
    line_class_enum = EnumType(
        "replace_100",
        "as_required",
        "menu_item",
        "kit_part",
        "consumable",
        "standard",
        name="lineclassenum",
        create_type=False,
    )
    procurement_status_enum = EnumType(
        "not_costed",
        "costed",
        "po_raised",
        "ordered",
        "received",
        "issued",
        name="procurementstatusenum",
        create_type=False,
    )
    match_status_enum = EnumType(
        "matched",
        "unmatched_bom",
        "unmatched_sheet",
        "ambiguous",
        name="matchstatusenum",
        create_type=False,
    )

    if is_postgres:
        for enum_type in [
            costing_stage_enum,
            line_class_enum,
            procurement_status_enum,
            match_status_enum,
        ]:
            enum_type.create(bind, checkfirst=True)
            # Prevent SQLAlchemy from trying to create the enum again on table create.
            enum_type._create_events = False

    op.create_table(
        "costing_template_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("engine_template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("xlsx_template_path", sa.String(length=512), nullable=True),
        sa.Column("sheet_name", sa.String(length=128), nullable=True),
        sa.Column("table_start_row", sa.Integer(), nullable=True),
        sa.Column("required_columns_json", sa.JSON(), nullable=True),
        sa.Column("header_cell_map_json", sa.JSON(), nullable=True),
        sa.Column("row_match_keys_json", sa.JSON(), nullable=True),
        sa.Column("programme_rules_json", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "costing_template_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "costing_template_profile_id",
            sa.Integer(),
            sa.ForeignKey("costing_template_profiles.id"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer(), nullable=True),
        sa.Column("group_no", sa.String(length=64), nullable=True),
        sa.Column("figure", sa.String(length=64), nullable=True),
        sa.Column("item_no", sa.String(length=64), nullable=True),
        sa.Column("oem_part_no", sa.String(length=120), nullable=True),
        sa.Column("system_part_number", sa.String(length=120), nullable=True),
        sa.Column("part_description", sa.String(length=255), nullable=True),
        sa.Column("default_class", line_class_enum, nullable=True),
        sa.Column("default_intended_supplier", sa.String(length=128), nullable=True),
        sa.Column("default_latest_supplier", sa.String(length=128), nullable=True),
        sa.Column("default_latest_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("default_menu_sell_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_menu", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_kit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_consumable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("default_qty_on_stock", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("default_qty_on_order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "costing_sheets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "costing_template_profile_id",
            sa.Integer(),
            sa.ForeignKey("costing_template_profiles.id"),
            nullable=True,
        ),
        sa.Column("template_version_snapshot", sa.Integer(), nullable=True),
        sa.Column("stage", costing_stage_enum, nullable=False, server_default="awaiting_sas"),
        sa.Column("issue", sa.String(length=64), nullable=True),
        sa.Column("auth", sa.String(length=64), nullable=True),
        sa.Column("job_no", sa.String(length=64), nullable=True),
        sa.Column("sn", sa.String(length=128), nullable=True),
        sa.Column("engine_no", sa.String(length=128), nullable=True),
        sa.Column("engine_desc", sa.String(length=255), nullable=True),
        sa.Column("date", sa.DateTime(), nullable=True),
        sa.Column("parts_replacement_cost", sa.Numeric(12, 2), nullable=True, server_default="0"),
        sa.Column("emergent_work_cost", sa.Numeric(12, 2), nullable=True, server_default="0"),
        sa.Column("menu_price_add", sa.Numeric(12, 2), nullable=True, server_default="0"),
        sa.Column("cost_booked", sa.Numeric(12, 2), nullable=True, server_default="0"),
        sa.Column("warning_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("job_id", name="uq_costing_sheets_job_id"),
    )

    op.create_table(
        "costing_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "costing_sheet_id",
            sa.Integer(),
            sa.ForeignKey("costing_sheets.id"),
            nullable=False,
        ),
        sa.Column(
            "part_requirement_id",
            sa.Integer(),
            sa.ForeignKey("part_requirements.id"),
            nullable=True,
        ),
        sa.Column("line_no", sa.Integer(), nullable=True),
        sa.Column("group_no", sa.String(length=64), nullable=True),
        sa.Column("figure", sa.String(length=64), nullable=True),
        sa.Column("item_no", sa.String(length=64), nullable=True),
        sa.Column("oem_part_no", sa.String(length=120), nullable=True),
        sa.Column("system_part_number", sa.String(length=120), nullable=True),
        sa.Column("part_description", sa.String(length=255), nullable=True),
        sa.Column("line_class", line_class_enum, nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_kit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_menu", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_consumable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("intended_supplier", sa.String(length=128), nullable=True),
        sa.Column("latest_supplier", sa.String(length=128), nullable=True),
        sa.Column("latest_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("menu_sell_price_unit", sa.Numeric(12, 2), nullable=True),
        sa.Column("rbb_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("qty_on_stock", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("qty_on_order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("qty_required", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("po_number", sa.String(length=120), nullable=True),
        sa.Column("unit_cost_confirmed", sa.Numeric(12, 2), nullable=True),
        sa.Column("line_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("procurement_status", procurement_status_enum, nullable=True, server_default="not_costed"),
        sa.Column("emergent_qty_required", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("emergent_line_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("emergent_reason", sa.Text(), nullable=True),
        sa.Column("match_status", match_status_enum, nullable=True, server_default="unmatched_sheet"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("costing_lines")
    op.drop_table("costing_sheets")
    op.drop_table("costing_template_lines")
    op.drop_table("costing_template_profiles")

    bind = op.get_bind()
    for enum_name in [
        "matchstatusenum",
        "procurementstatusenum",
        "lineclassenum",
        "costingstageenum",
    ]:
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
