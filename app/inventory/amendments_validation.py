"""Проверка бизнес-правил, хронологии и дефицита на проектируемой истории склада."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.inventory.amendments_dependency_validation import (
    check_batch_expiries,
    check_receipt_relocation,
    check_returns_and_cancellations,
)
from app.inventory.amendments_domain import AmendmentBlocker, AmendmentOperation
from app.inventory.calculator import sort_movements_chronological
from app.inventory.domain import (
    BatchSnapshot,
    MovementSnapshot,
)

_ZERO = Decimal("0.000")


def _check_future_dates(
    movements: Sequence[MovementSnapshot],
    today: date,
    blockers: list[AmendmentBlocker],
) -> None:
    """Проверяет отсутствие операций с датой в будущем."""
    for m in movements:
        if m.status == "active" and m.operation_date > today:
            blockers.append(
                AmendmentBlocker(
                    code="FUTURE_DATE",
                    message=f"Дата операции {m.operation_date} в будущем (сегодня {today})",
                    movement_id=m.id,
                    deficit_date=m.operation_date,
                    details={
                        "operation_date": m.operation_date.isoformat(),
                        "today": today.isoformat(),
                    },
                )
            )


def _check_doc_number_uniqueness(
    movements: Sequence[MovementSnapshot],
    blockers: list[AmendmentBlocker],
    active_location_docs: Sequence[tuple[int, int, str]] | None = None,
) -> None:
    """Проверяет уникальность номера активного документа на каждом объекте."""
    docs: dict[tuple[int, str], list[int]] = defaultdict(list)
    projected_ids: set[int] = set()
    for m in movements:
        if m.id is not None:
            projected_ids.add(m.id)
        if m.status == "active" and m.id is not None:
            docs[(m.location_id, m.doc_number)].append(m.id)

    external_docs: dict[tuple[int, str], int] = {}
    if active_location_docs:
        for m_id, loc_id, doc_num in active_location_docs:
            if m_id not in projected_ids:
                external_docs[(loc_id, doc_num)] = m_id

    for (loc_id, doc_num), m_ids in docs.items():
        if len(m_ids) > 1:
            for m_id in m_ids:
                blockers.append(
                    AmendmentBlocker(
                        code="DUPLICATE_DOC_NUMBER",
                        message=f"Документ с номером '{doc_num}' уже зарегистрирован на объекте",
                        movement_id=m_id,
                        details={"doc_number": doc_num, "location_id": loc_id},
                    )
                )
        elif (loc_id, doc_num) in external_docs:
            ext_id = external_docs[(loc_id, doc_num)]
            for m_id in m_ids:
                blockers.append(
                    AmendmentBlocker(
                        code="DUPLICATE_DOC_NUMBER",
                        message=f"Документ с номером '{doc_num}' уже зарегистрирован на объекте",
                        movement_id=m_id,
                        details={
                            "doc_number": doc_num,
                            "location_id": loc_id,
                            "conflicting_movement_id": ext_id,
                        },
                    )
                )


def _check_chronological_sufficiency(
    projected_movements: Sequence[MovementSnapshot],
    blockers: list[AmendmentBlocker],
) -> None:
    """Проверяет хронологическую неотрицательность остатков по каждой партии."""
    active_mvs = [m for m in projected_movements if m.status == "active"]
    sorted_mvs = sort_movements_chronological(active_mvs)
    balances: dict[tuple[int, int], Decimal] = defaultdict(lambda: _ZERO)

    for m in sorted_mvs:
        if m.type == "receipt" and m.batch_id is not None:
            balances[(m.location_id, m.batch_id)] += m.quantity
        elif m.type == "consume":
            for alloc in m.allocations:
                key = (m.location_id, alloc.batch_id)
                balances[key] -= alloc.quantity
                if balances[key] < _ZERO:
                    deficit = abs(balances[key])
                    blockers.append(
                        AmendmentBlocker(
                            code="HISTORICAL_DEFICIT",
                            message=(
                                f"Дефицит {deficit} по партии {alloc.batch_id} "
                                f"на дату {m.operation_date.isoformat()}"
                            ),
                            movement_id=m.id,
                            dependent_movement_id=m.id,
                            batch_id=alloc.batch_id,
                            allocation_id=alloc.id,
                            deficit_qty=deficit,
                            deficit_date=m.operation_date,
                            details={
                                "conflicting_doc_number": m.doc_number,
                                "location_id": m.location_id,
                            },
                        )
                    )
        elif m.type == "writeoff" and m.batch_id is not None:
            key = (m.location_id, m.batch_id)
            balances[key] -= m.quantity
            if balances[key] < _ZERO:
                deficit = abs(balances[key])
                blockers.append(
                    AmendmentBlocker(
                        code="HISTORICAL_DEFICIT",
                        message=(
                            f"Дефицит {deficit} по партии {m.batch_id} "
                            f"на дату {m.operation_date.isoformat()}"
                        ),
                        movement_id=m.id,
                        dependent_movement_id=m.id,
                        batch_id=m.batch_id,
                        deficit_qty=deficit,
                        deficit_date=m.operation_date,
                        details={
                            "conflicting_doc_number": m.doc_number,
                            "location_id": m.location_id,
                        },
                    )
                )
        elif m.type == "return" and m.batch_id is not None:
            balances[(m.location_id, m.batch_id)] += m.quantity
        elif m.type == "correction" and m.batch_id is not None:
            key = (m.location_id, m.batch_id)
            balances[key] += m.quantity
            if balances[key] < _ZERO:
                deficit = abs(balances[key])
                blockers.append(
                    AmendmentBlocker(
                        code="HISTORICAL_DEFICIT",
                        message=(
                            f"Дефицит {deficit} по партии {m.batch_id} "
                            f"на дату {m.operation_date.isoformat()}"
                        ),
                        movement_id=m.id,
                        dependent_movement_id=m.id,
                        batch_id=m.batch_id,
                        deficit_qty=deficit,
                        deficit_date=m.operation_date,
                        details={
                            "conflicting_doc_number": m.doc_number,
                            "location_id": m.location_id,
                        },
                    )
                )


def validate_projected_history(
    projected_batches: Sequence[BatchSnapshot],
    projected_movements: Sequence[MovementSnapshot],
    original_movements: Sequence[MovementSnapshot],
    operations: Sequence[AmendmentOperation],
    today: date,
    active_location_docs: Sequence[tuple[int, int, str]] | None = None,
) -> list[AmendmentBlocker]:
    """Проводит полную доменную проверку проектируемой истории на наличие блокеров."""
    blockers: list[AmendmentBlocker] = []
    _check_future_dates(projected_movements, today, blockers)
    _check_doc_number_uniqueness(
        projected_movements, blockers, active_location_docs=active_location_docs
    )
    check_receipt_relocation(projected_movements, original_movements, operations, blockers)
    check_returns_and_cancellations(projected_movements, blockers)
    check_batch_expiries(projected_movements, projected_batches, blockers)
    _check_chronological_sufficiency(projected_movements, blockers)
    return blockers
