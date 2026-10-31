"""add org ownership to store and picklist tables

Revision ID: c1d2e3f4a5b6
Revises: bb8c9d0e1f2a
Create Date: 2026-02-08 20:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "bb8c9d0e1f2a"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _index_exists(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _fk_exists(inspector, table_name: str, fk_name: str) -> bool:
    return fk_name in {fk["name"] for fk in inspector.get_foreign_keys(table_name)}


def _unique_names(inspector, table_name: str) -> set[str]:
    return {u["name"] for u in inspector.get_unique_constraints(table_name)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1) Add nullable columns first so we can backfill safely.
    if not _column_exists(inspector, "store_items", "organization_id"):
        with op.batch_alter_table("store_items") as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    if not _column_exists(inspector, "pick_lists", "organization_id"):
        with op.batch_alter_table("pick_lists") as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    if not _column_exists(inspector, "pick_list_items", "organization_id"):
        with op.batch_alter_table("pick_list_items") as batch_op:
            batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    # 2) Backfill using authoritative parent ownership.
    # StoreItem  <- TemplateItem.organization_id
    bind.execute(
        sa.text(
            """
            UPDATE store_items
            SET organization_id = (
                SELECT ti.organization_id
                FROM template_items ti
                WHERE ti.id = store_items.template_item_id
            )
            WHERE organization_id IS NULL
            """
        )
    )

    # PickList <- Job.organization_id
    bind.execute(
        sa.text(
            """
            UPDATE pick_lists
            SET organization_id = (
                SELECT j.organization_id
                FROM jobs j
                WHERE j.id = pick_lists.job_id
            )
            WHERE organization_id IS NULL
            """
        )
    )

    # PickListItem <- PickList.organization_id
    bind.execute(
        sa.text(
            """
            UPDATE pick_list_items
            SET organization_id = (
                SELECT pl.organization_id
                FROM pick_lists pl
                WHERE pl.id = pick_list_items.pick_list_id
            )
            WHERE organization_id IS NULL
            """
        )
    )

    # 3) Fail loudly if backfill left orphans.
    for table_name in ("store_items", "pick_lists", "pick_list_items"):
        missing = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE organization_id IS NULL")
        ).scalar_one()
        if missing:
            raise RuntimeError(
                f"Migration aborted: {table_name} has {missing} row(s) without organization ownership."
            )

    inspector = sa.inspect(bind)
    store_unique_names = _unique_names(inspector, "store_items")

    # 4) Constraints + indexes + non-null.
    with op.batch_alter_table("store_items") as batch_op:
        # Drop legacy global barcode uniqueness to allow same barcode across orgs.
        for name in ("uq_store_items_barcode", "store_items_barcode_key"):
            if name in store_unique_names:
                batch_op.drop_constraint(name, type_="unique")
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        if not _index_exists(inspector, "store_items", "ix_store_items_organization_id"):
            batch_op.create_index("ix_store_items_organization_id", ["organization_id"], unique=False)
        if not _fk_exists(inspector, "store_items", "fk_store_items_organization_id"):
            batch_op.create_foreign_key(
                "fk_store_items_organization_id",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="CASCADE",
            )
        try:
            batch_op.create_unique_constraint(
                "uq_store_items_org_barcode",
                ["organization_id", "barcode"],
            )
        except Exception:
            pass

    with op.batch_alter_table("pick_lists") as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        if not _index_exists(inspector, "pick_lists", "ix_pick_lists_organization_id"):
            batch_op.create_index("ix_pick_lists_organization_id", ["organization_id"], unique=False)
        if not _fk_exists(inspector, "pick_lists", "fk_pick_lists_organization_id"):
            batch_op.create_foreign_key(
                "fk_pick_lists_organization_id",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="CASCADE",
            )

    with op.batch_alter_table("pick_list_items") as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        if not _index_exists(inspector, "pick_list_items", "ix_pick_list_items_organization_id"):
            batch_op.create_index("ix_pick_list_items_organization_id", ["organization_id"], unique=False)
        if not _fk_exists(inspector, "pick_list_items", "fk_pick_list_items_organization_id"):
            batch_op.create_foreign_key(
                "fk_pick_list_items_organization_id",
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade():
    with op.batch_alter_table("pick_list_items") as batch_op:
        try:
            batch_op.drop_constraint("fk_pick_list_items_organization_id", type_="foreignkey")
        except Exception:
            pass
        try:
            batch_op.drop_index("ix_pick_list_items_organization_id")
        except Exception:
            pass
        batch_op.drop_column("organization_id")

    with op.batch_alter_table("pick_lists") as batch_op:
        try:
            batch_op.drop_constraint("fk_pick_lists_organization_id", type_="foreignkey")
        except Exception:
            pass
        try:
            batch_op.drop_index("ix_pick_lists_organization_id")
        except Exception:
            pass
        batch_op.drop_column("organization_id")

    with op.batch_alter_table("store_items") as batch_op:
        try:
            batch_op.drop_constraint("uq_store_items_org_barcode", type_="unique")
        except Exception:
            pass
        try:
            batch_op.drop_constraint("fk_store_items_organization_id", type_="foreignkey")
        except Exception:
            pass
        try:
            batch_op.drop_index("ix_store_items_organization_id")
        except Exception:
            pass
        batch_op.drop_column("organization_id")
        try:
            batch_op.create_unique_constraint("uq_store_items_barcode", ["barcode"])
        except Exception:
            pass
