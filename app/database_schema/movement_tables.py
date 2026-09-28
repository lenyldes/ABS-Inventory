"""Создание и удаление таблиц движений и распределений (movements, allocations)."""

import sqlalchemy as sa

from alembic import op


def create_movement_tables() -> None:
    """Создаёт таблицы движений и распределений по партиям."""
    op.create_table(
        "movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("doc_number", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("parent_movement_id", sa.Integer(), nullable=True),
        sa.Column("parent_allocation_id", sa.Integer(), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'cancelled')", name="chk_movements_status"),
        sa.CheckConstraint(
            "type IN ('receipt', 'consume', 'writeoff', 'return', 'correction')",
            name="chk_movements_type",
        ),
        sa.CheckConstraint("current_version >= 1", name="chk_movements_current_version"),
        sa.CheckConstraint("quantity != 0", name="chk_movements_quantity_not_zero"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_movement_id"], ["movements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_movements_batch_id"), "movements", ["batch_id"], unique=False)
    op.create_index(op.f("ix_movements_created_at"), "movements", ["created_at"], unique=False)
    op.create_index(op.f("ix_movements_doc_number"), "movements", ["doc_number"], unique=False)
    op.create_index(op.f("ix_movements_item_id"), "movements", ["item_id"], unique=False)
    op.create_index(op.f("ix_movements_location_id"), "movements", ["location_id"], unique=False)
    op.create_index(
        op.f("ix_movements_operation_date"), "movements", ["operation_date"], unique=False
    )
    op.create_index(
        op.f("ix_movements_parent_allocation_id"),
        "movements",
        ["parent_allocation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movements_parent_movement_id"), "movements", ["parent_movement_id"], unique=False
    )
    op.create_index(
        op.f("ix_movements_purchase_order_id"), "movements", ["purchase_order_id"], unique=False
    )
    op.create_index(op.f("ix_movements_status"), "movements", ["status"], unique=False)
    op.create_index(op.f("ix_movements_supplier_id"), "movements", ["supplier_id"], unique=False)
    op.create_index(op.f("ix_movements_type"), "movements", ["type"], unique=False)
    op.create_index(
        "uq_movements_location_doc_active",
        "movements",
        ["location_id", "doc_number"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "movement_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movement_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity > 0", name="chk_movement_allocations_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="chk_movement_allocations_unit_price"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["movement_id"], ["movements.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_movement_allocations_batch_id"), "movement_allocations", ["batch_id"], unique=False
    )
    op.create_index(
        op.f("ix_movement_allocations_movement_id"),
        "movement_allocations",
        ["movement_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_movements_parent_allocation_id",
        "movements",
        "movement_allocations",
        ["parent_allocation_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )


def drop_movement_tables() -> None:
    """Удаляет таблицы движений и распределений."""
    op.drop_constraint("fk_movements_parent_allocation_id", "movements", type_="foreignkey")
    op.drop_index(op.f("ix_movement_allocations_movement_id"), table_name="movement_allocations")
    op.drop_index(op.f("ix_movement_allocations_batch_id"), table_name="movement_allocations")
    op.drop_table("movement_allocations")
    op.drop_index(
        "uq_movements_location_doc_active",
        table_name="movements",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(op.f("ix_movements_type"), table_name="movements")
    op.drop_index(op.f("ix_movements_supplier_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_status"), table_name="movements")
    op.drop_index(op.f("ix_movements_purchase_order_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_parent_movement_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_parent_allocation_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_operation_date"), table_name="movements")
    op.drop_index(op.f("ix_movements_location_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_item_id"), table_name="movements")
    op.drop_index(op.f("ix_movements_doc_number"), table_name="movements")
    op.drop_index(op.f("ix_movements_created_at"), table_name="movements")
    op.drop_index(op.f("ix_movements_batch_id"), table_name="movements")
    op.drop_table("movements")
