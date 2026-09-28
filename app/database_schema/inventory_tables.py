"""Создание и удаление таблиц партий и блокировок (batches, stock_locks)."""

import sqlalchemy as sa

from alembic import op


def create_inventory_tables() -> None:
    """Создаёт таблицы партий поступлений и служебных блокировок остатка."""
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(length=128), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("receipt_doc_number", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("unit_price >= 0", name="chk_batches_unit_price"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_batches_fefo",
        "batches",
        ["expiry_date", "receipt_date", "created_at", "id"],
        unique=False,
    )
    op.create_index(op.f("ix_batches_expiry_date"), "batches", ["expiry_date"], unique=False)
    op.create_index(op.f("ix_batches_item_id"), "batches", ["item_id"], unique=False)
    op.create_index(op.f("ix_batches_location_id"), "batches", ["location_id"], unique=False)
    op.create_index(op.f("ix_batches_receipt_date"), "batches", ["receipt_date"], unique=False)

    op.create_table(
        "stock_locks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "location_id", name="uq_stock_locks_item_location"),
    )
    op.create_index(op.f("ix_stock_locks_item_id"), "stock_locks", ["item_id"], unique=False)
    op.create_index(
        op.f("ix_stock_locks_location_id"), "stock_locks", ["location_id"], unique=False
    )


def drop_inventory_tables() -> None:
    """Удаляет таблицы блокировок и партий."""
    op.drop_index(op.f("ix_stock_locks_location_id"), table_name="stock_locks")
    op.drop_index(op.f("ix_stock_locks_item_id"), table_name="stock_locks")
    op.drop_table("stock_locks")
    op.drop_index(op.f("ix_batches_receipt_date"), table_name="batches")
    op.drop_index(op.f("ix_batches_location_id"), table_name="batches")
    op.drop_index(op.f("ix_batches_item_id"), table_name="batches")
    op.drop_index(op.f("ix_batches_expiry_date"), table_name="batches")
    op.drop_index("idx_batches_fefo", table_name="batches")
    op.drop_table("batches")
