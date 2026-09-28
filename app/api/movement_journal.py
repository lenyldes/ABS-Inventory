"""Построение элементов журнала движений с расчётом отклонений от FEFO."""

from sqlalchemy.orm import Session

from app.api.movement_schemas import (
    AllocationResponse,
    MovementListItem,
    MovementWarningResponse,
)
from app.inventory.calculator import sort_movements_chronological
from app.inventory.common_validation import load_history
from app.inventory.domain import BatchSnapshot, MovementSnapshot
from app.inventory.fefo import detect_fefo_deviation
from app.models.inventory import Movement


class MovementJournalBuilder:
    """Кэширующий построитель элементов журнала с проверкой предупреждений."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._history_cache: dict[
            tuple[int, int],
            tuple[list[BatchSnapshot], list[MovementSnapshot]],
        ] = {}

    def build_item(self, m: Movement) -> MovementListItem:
        """Преобразует ORM-модель движения в элемент схемы ответа с расчётом warnings."""
        warnings: list[MovementWarningResponse] = []
        if m.type == "consume":
            pair = (m.item_id, m.location_id)
            if pair not in self._history_cache:
                _, _, b_snaps, m_snaps = load_history(self.db, m.item_id, m.location_id)
                self._history_cache[pair] = (b_snaps, m_snaps)
            b_snaps, m_snaps = self._history_cache[pair]
            consume_snap = next((snap for snap in m_snaps if snap.id == m.id), None)
            if consume_snap:
                sorted_history = sort_movements_chronological(m_snaps)
                consume_idx = next(
                    (i for i, s in enumerate(sorted_history) if s.id == m.id),
                    len(sorted_history),
                )
                prior_m = sorted_history[:consume_idx]
                devs = detect_fefo_deviation(consume_snap, b_snaps, prior_m)
                warnings = [
                    MovementWarningResponse(
                        code=w.code,
                        message=w.message,
                        details=w.details,
                    )
                    for w in devs
                ]

        allocs = [
            AllocationResponse(
                id=a.id,
                batch_id=a.batch_id,
                quantity=a.quantity,
                unit_price=a.unit_price,
            )
            for a in (m.allocations or [])
        ]

        return MovementListItem(
            id=m.id,
            operation_date=m.operation_date,
            created_at=m.created_at,
            sku=m.item.sku,
            location=m.location.code,
            type=m.type,
            quantity=m.quantity,
            doc_number=m.doc_number,
            reason=m.reason,
            allocations=allocs,
            warnings=warnings,
        )
