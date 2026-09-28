"""Создание и удаление таблиц закупок (purchase_orders, supplier_conditions)."""

import sqlalchemy as sa

from alembic import op


def create_procurement_tables() -> None:
    """Создаёт таблицы ожидаемых поставок и закупочных условий."""
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("doc_number", sa.String(length=64), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=False),
        sa.Column("expected_qty", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("received_qty", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("pending_qty", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delayed', 'partially_received', 'received', 'cancelled')",
            name="chk_purchase_orders_status",
        ),
        sa.CheckConstraint("expected_qty > 0", name="chk_purchase_orders_expected_qty"),
        sa.CheckConstraint("pending_qty >= 0", name="chk_purchase_orders_pending_qty"),
        sa.CheckConstraint(
            "received_qty <= expected_qty", name="chk_purchase_orders_received_le_expected"
        ),
        sa.CheckConstraint("received_qty >= 0", name="chk_purchase_orders_received_qty"),
        sa.CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0", name="chk_purchase_orders_unit_price"
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("location_id", "doc_number", name="uq_purchase_orders_location_doc"),
    )
    op.create_index(
        op.f("ix_purchase_orders_doc_number"), "purchase_orders", ["doc_number"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_orders_expected_date"), "purchase_orders", ["expected_date"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_orders_item_id"), "purchase_orders", ["item_id"], unique=False
    )
    op.create_index(
        op.f("ix_purchase_orders_location_id"), "purchase_orders", ["location_id"], unique=False
    )
    op.create_index(op.f("ix_purchase_orders_status"), "purchase_orders", ["status"], unique=False)
    op.create_index(
        op.f("ix_purchase_orders_supplier_id"), "purchase_orders", ["supplier_id"], unique=False
    )

    op.create_table(
        "supplier_conditions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False),
        sa.Column("package_size", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("min_order_qty", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("estimated_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "estimated_price IS NULL OR estimated_price >= 0",
            name="chk_supplier_conditions_estimated_price",
        ),
        sa.CheckConstraint("lead_time_days >= 1", name="chk_supplier_conditions_lead_time_days"),
        sa.CheckConstraint("min_order_qty > 0", name="chk_supplier_conditions_min_order_qty"),
        sa.CheckConstraint("package_size > 0", name="chk_supplier_conditions_package_size"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "supplier_id", name="uq_supplier_conditions_item_supplier"),
    )
    op.create_index(
        op.f("ix_supplier_conditions_item_id"), "supplier_conditions", ["item_id"], unique=False
    )
    op.create_index(
        op.f("ix_supplier_conditions_supplier_id"),
        "supplier_conditions",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "uq_item_primary_supplier",
        "supplier_conditions",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("is_primary = true"),
    )


def drop_procurement_tables() -> None:
    """Удаляет таблицы закупок."""
    op.drop_index(
        "uq_item_primary_supplier",
        table_name="supplier_conditions",
        postgresql_where=sa.text("is_primary = true"),
    )
    op.drop_index(op.f("ix_supplier_conditions_supplier_id"), table_name="supplier_conditions")
    op.drop_index(op.f("ix_supplier_conditions_item_id"), table_name="supplier_conditions")
    op.drop_table("supplier_conditions")
    op.drop_index(op.f("ix_purchase_orders_supplier_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_status"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_location_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_item_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_expected_date"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_doc_number"), table_name="purchase_orders")
    op.drop_table("purchase_orders")
