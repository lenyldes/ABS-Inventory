"""backfill_movement_versions

Revision ID: 7a1b2c3d4e5f
Revises: 2df052e2bbd9
Create Date: 2026-09-28 14:00:00.000000

"""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "2df052e2bbd9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Заполняет версию 1 для существующих движений без вымышленной истории."""
    bind = op.get_bind()

    # Исключаем движения, у которых уже есть версия 1
    existing_version_ids = (
        sa.select(sa.column("movement_id"))
        .select_from(
            sa.table("movement_versions", sa.column("movement_id"), sa.column("version_num"))
        )
        .where(sa.column("version_num") == 1)
    )

    movements_table = sa.table(
        "movements",
        sa.column("id"),
        sa.column("operation_date"),
        sa.column("created_at"),
        sa.column("item_id"),
        sa.column("location_id"),
        sa.column("type"),
        sa.column("quantity"),
        sa.column("doc_number"),
        sa.column("batch_id"),
        sa.column("reason"),
        sa.column("parent_movement_id"),
        sa.column("parent_allocation_id"),
        sa.column("purchase_order_id"),
        sa.column("supplier_id"),
        sa.column("status"),
    )

    query = (
        sa.select(movements_table)
        .where(movements_table.c.id.not_in(existing_version_ids))
        .order_by(movements_table.c.id.asc())
    )

    movements = bind.execute(query).fetchall()
    if not movements:
        return

    # Загружаем распределения для затронутых движений
    movement_ids = [m.id for m in movements]
    allocs_table = sa.table(
        "movement_allocations",
        sa.column("id"),
        sa.column("movement_id"),
        sa.column("batch_id"),
        sa.column("quantity"),
        sa.column("unit_price"),
    )
    alloc_query = (
        sa.select(allocs_table)
        .where(allocs_table.c.movement_id.in_(movement_ids))
        .order_by(allocs_table.c.id.asc())
    )

    allocs = bind.execute(alloc_query).fetchall()
    alloc_map: dict[int, list[dict[str, object]]] = defaultdict(list)
    for a in allocs:
        alloc_map[a.movement_id].append(
            {
                "id": a.id,
                "batch_id": a.batch_id,
                "quantity": f"{Decimal(str(a.quantity)):.3f}",
                "unit_price": f"{Decimal(str(a.unit_price)):.2f}",
            }
        )

    versions_table = sa.table(
        "movement_versions",
        sa.column("movement_id", sa.Integer),
        sa.column("version_num", sa.Integer),
        sa.column("action", sa.String),
        sa.column("reason", sa.Text),
        sa.column("snapshot", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    inserts = []
    for m in movements:
        m_allocs = alloc_map.get(m.id, [])
        op_date_str = (
            m.operation_date.isoformat()
            if hasattr(m.operation_date, "isoformat")
            else str(m.operation_date)
        )
        snapshot = {
            "id": m.id,
            "operation_date": op_date_str,
            "type": m.type,
            "quantity": f"{Decimal(str(m.quantity)):.3f}",
            "doc_number": m.doc_number,
            "status": m.status,
            "item_id": m.item_id,
            "location_id": m.location_id,
            "batch_id": m.batch_id,
            "reason": m.reason,
            "parent_movement_id": m.parent_movement_id,
            "parent_allocation_id": m.parent_allocation_id,
            "purchase_order_id": m.purchase_order_id,
            "supplier_id": m.supplier_id,
            "allocations": m_allocs,
        }
        inserts.append(
            {
                "movement_id": m.id,
                "version_num": 1,
                "action": "create",
                "reason": "Первичный ввод",
                "snapshot": snapshot,
                "created_at": m.created_at,
            }
        )

    if inserts:
        op.bulk_insert(versions_table, inserts)


def downgrade() -> None:
    """Downgrade schema: сохраняет движения и версии при откате."""
    pass
