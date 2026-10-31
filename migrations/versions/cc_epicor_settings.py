"""add epicor settings

Revision ID: cc_epicor_settings
Revises: bb_add_costing_models
Create Date: 2025-12-07 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "cc_epicor_settings"
down_revision = "bb_add_costing_models"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        auth_enum = postgresql.ENUM("api_key", "oauth", name="epicorauthmethodenum", create_type=False)
        env_enum = postgresql.ENUM("prod", "test", name="epicorenvironmentenum", create_type=False)
        write_enum = postgresql.ENUM("none", "dmt", "rest", name="epicorwritemodeenum", create_type=False)
        for enum_type in [auth_enum, env_enum, write_enum]:
            enum_type.create(bind, checkfirst=True)
            # Prevent SQLAlchemy from trying to create the enum again on table create.
            enum_type._create_events = False
        is_active_default = sa.text("true")
    else:
        auth_enum = sa.Enum("api_key", "oauth", name="epicorauthmethodenum")
        env_enum = sa.Enum("prod", "test", name="epicorenvironmentenum")
        write_enum = sa.Enum("none", "dmt", "rest", name="epicorwritemodeenum")
        auth_enum.create(bind, checkfirst=True)
        env_enum.create(bind, checkfirst=True)
        write_enum.create(bind, checkfirst=True)
        is_active_default = sa.text("1")

    op.create_table(
        "epicor_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=True),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=128), nullable=True),
        sa.Column("plant", sa.String(length=128), nullable=True),
        sa.Column("environment", env_enum, nullable=True, server_default="test"),
        sa.Column("auth_method", auth_enum, nullable=False, server_default="api_key"),
        sa.Column("api_key_env_var", sa.String(length=128), nullable=True),
        sa.Column("oauth_client_id", sa.String(length=255), nullable=True),
        sa.Column("oauth_tenant_id", sa.String(length=255), nullable=True),
        sa.Column("oauth_scope", sa.String(length=255), nullable=True),
        sa.Column("baq_part_cost", sa.String(length=128), nullable=True),
        sa.Column("baq_stock", sa.String(length=128), nullable=True),
        sa.Column("baq_po_status", sa.String(length=128), nullable=True),
        sa.Column("write_mode", write_enum, nullable=True, server_default="none"),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("last_test_status", sa.String(length=32), nullable=True),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("last_sample_at", sa.DateTime(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=is_active_default),
    )


def downgrade():
    op.drop_table("epicor_settings")
    bind = op.get_bind()
    for enum_name in ["epicorwritemodeenum", "epicorenvironmentenum", "epicorauthmethodenum"]:
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
