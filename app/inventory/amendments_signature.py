"""Каноническая сериализация и вычисление криптографической подписи состояния склада."""

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from app.inventory.amendments_domain import AmendmentOperation
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder


def _serialize_movement(movement: Movement) -> dict[str, Any]:
    """Сериализует движение и его распределения в детерминированную структуру."""
    allocations = [
        {
            "id": a.id,
            "batch_id": a.batch_id,
            "quantity": f"{Decimal(str(a.quantity)):.3f}",
            "unit_price": f"{Decimal(str(a.unit_price)):.2f}",
        }
        for a in sorted(movement.allocations or [], key=lambda x: (x.id or 0, x.batch_id))
    ]
    return {
        "id": movement.id,
        "operation_date": (
            movement.operation_date.isoformat()
            if hasattr(movement.operation_date, "isoformat")
            else str(movement.operation_date)
        ),
        "type": movement.type,
        "quantity": f"{Decimal(str(movement.quantity)):.3f}",
        "doc_number": movement.doc_number,
        "status": movement.status,
        "batch_id": movement.batch_id,
        "current_version": movement.current_version,
        "parent_movement_id": movement.parent_movement_id,
        "parent_allocation_id": movement.parent_allocation_id,
        "purchase_order_id": movement.purchase_order_id,
        "allocations": allocations,
    }


def _serialize_batch(batch: Batch) -> dict[str, Any]:
    """Сериализует партию в детерминированную структуру."""
    return {
        "id": batch.id,
        "batch_number": batch.batch_number,
        "receipt_date": (
            batch.receipt_date.isoformat()
            if hasattr(batch.receipt_date, "isoformat")
            else str(batch.receipt_date)
        ),
        "expiry_date": (
            batch.expiry_date.isoformat()
            if batch.expiry_date and hasattr(batch.expiry_date, "isoformat")
            else (str(batch.expiry_date) if batch.expiry_date else None)
        ),
        "unit_price": f"{Decimal(str(batch.unit_price)):.2f}",
        "receipt_doc_number": batch.receipt_doc_number,
        "location_id": batch.location_id,
    }


def _serialize_purchase_order(order: PurchaseOrder) -> dict[str, Any]:
    """Сериализует заказ поставщику в детерминированную структуру."""
    return {
        "id": order.id,
        "status": order.status,
        "expected_qty": f"{Decimal(str(order.expected_qty)):.3f}",
        "received_qty": f"{Decimal(str(order.received_qty)):.3f}",
        "pending_qty": f"{Decimal(str(order.pending_qty)):.3f}",
    }


def compute_state_signature(
    pairs: Sequence[tuple[int, int]],
    movements: Sequence[Movement],
    batches: Sequence[Batch],
    purchase_orders: Sequence[PurchaseOrder],
    operations: Sequence[AmendmentOperation] | None = None,
) -> str:
    """Вычисляет каноническую криптографическую подпись значимого состояния склада."""
    sorted_pairs = sorted(set(pairs), key=lambda p: (p[0], p[1]))
    canonical_data: dict[str, Any] = {
        "pairs": [list(p) for p in sorted_pairs],
        "movements": [_serialize_movement(m) for m in sorted(movements, key=lambda x: x.id)],
        "batches": [_serialize_batch(b) for b in sorted(batches, key=lambda x: x.id)],
        "purchase_orders": [
            _serialize_purchase_order(po) for po in sorted(purchase_orders, key=lambda x: x.id)
        ],
        "expected_versions": [
            {"movement_id": op.movement_id, "expected_version": op.expected_version}
            for op in sorted(operations or [], key=lambda x: x.movement_id)
        ],
    }
    raw_json = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    return f"sig_{digest}"
