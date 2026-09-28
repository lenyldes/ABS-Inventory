"""Создание и удаление таблиц справочников каталога (items, locations, suppliers)."""

import sqlalchemy as sa

from alembic import op


def create_catalog_tables() -> None:
    """Создаёт таблицы справочников товаров, объектов и поставщиков."""
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_items_category"), "items", ["category"], unique=False)
    op.create_index(op.f("ix_items_sku"), "items", ["sku"], unique=True)

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_locations_code"), "locations", ["code"], unique=True)

    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_suppliers_supplier_id"), "suppliers", ["supplier_id"], unique=True)


def drop_catalog_tables() -> None:
    """Удаляет таблицы справочников каталога."""
    op.drop_index(op.f("ix_suppliers_supplier_id"), table_name="suppliers")
    op.drop_table("suppliers")
    op.drop_index(op.f("ix_locations_code"), table_name="locations")
    op.drop_table("locations")
    op.drop_index(op.f("ix_items_sku"), table_name="items")
    op.drop_index(op.f("ix_items_category"), table_name="items")
    op.drop_table("items")
