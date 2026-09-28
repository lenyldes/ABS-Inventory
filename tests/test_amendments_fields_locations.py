"""Чистые тесты для задачи 2.4: проверка полей, уникальности документов и переноса прихода."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.inventory.amendments_domain import AmendmentOperation
from app.inventory.amendments_service import simulate_amendment_set
from app.inventory.domain import (
    AllocationSnapshot,
    BatchSnapshot,
    MovementSnapshot,
)
from app.inventory.exceptions import AmendmentValidationError


def _make_batch(
    b_id: int = 1,
    loc_id: int = 1,
    rec_date: date = date(2026, 9, 1),
    doc_num: str = "DOC-1",
) -> BatchSnapshot:
    return BatchSnapshot(
        id=b_id,
        item_id=1,
        location_id=loc_id,
        batch_number=f"B-{b_id}",
        receipt_date=rec_date,
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("100.00"),
        receipt_doc_number=doc_num,
        created_at=datetime(2026, 9, 1, 10, 0),
    )


def test_cannot_change_sku_raises_validation_error() -> None:
    """Попытка изменить SKU через поля правки категорически запрещена."""
    b = _make_batch()
    rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="DOC-1",
        batch_id=1,
    )
    op = AmendmentOperation(
        movement_id=1,
        action="update",
        raw_fields={"sku": "NEW-SKU-99"},
    )
    with pytest.raises(AmendmentValidationError) as exc:
        simulate_amendment_set(
            batches=[b],
            movements=[rec],
            operations=[op],
            today=date(2026, 9, 10),
        )
    assert exc.value.code == "CANNOT_CHANGE_SKU"


def test_cannot_change_location_on_consume() -> None:
    """Смена объекта разрешена только для прихода; для расхода это запрещено."""
    b = _make_batch()
    cons = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        created_at=datetime(2026, 9, 2, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("3.000"),
        doc_number="CONS-2",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("3.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )
    op = AmendmentOperation(
        movement_id=2,
        action="update",
        location_id=2,
    )
    with pytest.raises(AmendmentValidationError) as exc:
        simulate_amendment_set(
            batches=[b],
            movements=[cons],
            operations=[op],
            today=date(2026, 9, 10),
        )
    assert exc.value.code == "INVALID_LOCATION_CHANGE"


def test_receipt_metadata_sync_to_batch() -> None:
    """При обновлении прихода (дата, номер документа, объект) синхронизируются метаданные партии."""
    b = _make_batch(1, loc_id=1, rec_date=date(2026, 9, 1), doc_num="DOC-OLD")
    rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="DOC-OLD",
        batch_id=1,
    )
    op = AmendmentOperation(
        movement_id=1,
        action="update",
        operation_date=date(2026, 9, 3),
        doc_number="DOC-NEW",
        location_id=2,
    )
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec],
        operations=[op],
        today=date(2026, 9, 10),
    )
    assert res.can_apply
    proj_b = next(pb for pb in res.projected_batches if pb.id == 1)
    assert proj_b.receipt_date == date(2026, 9, 3)
    assert proj_b.receipt_doc_number == "DOC-NEW"
    assert proj_b.location_id == 2


def test_duplicate_doc_number_on_same_location_blocks_amendment() -> None:
    """Изменение номера документа на уже существующий активный на том же объекте отклоняется."""
    b1 = _make_batch(1, doc_num="DOC-A")
    b2 = _make_batch(2, doc_num="DOC-B")
    rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="DOC-A",
        batch_id=1,
    )
    rec2 = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="DOC-B",
        batch_id=2,
    )

    # Меняем номер второго документа на DOC-A (дубликат на объекте 1)
    op = AmendmentOperation(
        movement_id=2,
        action="update",
        doc_number="DOC-A",
    )
    res = simulate_amendment_set(
        batches=[b1, b2],
        movements=[rec1, rec2],
        operations=[op],
        today=date(2026, 9, 10),
    )
    assert not res.can_apply
    assert any(bl.code == "DUPLICATE_DOC_NUMBER" for bl in res.blockers)


def test_duplicate_doc_number_with_external_active_movement_blocks_amendment() -> None:
    """Номер документа, занятый активным движением другого товара на объекте, отклоняется."""
    b1 = _make_batch(1, doc_num="DOC-A")
    rec1 = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("5.000"),
        doc_number="DOC-A",
        batch_id=1,
    )
    external_docs = [(99, 1, "DOC-EXT")]

    op = AmendmentOperation(
        movement_id=1,
        action="update",
        doc_number="DOC-EXT",
    )
    res = simulate_amendment_set(
        batches=[b1],
        movements=[rec1],
        operations=[op],
        today=date(2026, 9, 10),
        active_location_docs=external_docs,
    )
    assert not res.can_apply
    dup_blocker = next(bl for bl in res.blockers if bl.code == "DUPLICATE_DOC_NUMBER")
    assert dup_blocker.details["conflicting_movement_id"] == 99


def test_receipt_relocation_rejected_if_dependent_operations_on_old_location() -> None:
    """Перемещение прихода отклоняется блокером при наличии зависимого расхода на старом объекте."""
    b = _make_batch(1, loc_id=1)
    rec = MovementSnapshot(
        id=1,
        operation_date=date(2026, 9, 1),
        created_at=datetime(2026, 9, 1, 10, 0),
        item_id=1,
        location_id=1,
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="REC-1",
        batch_id=1,
    )
    cons = MovementSnapshot(
        id=2,
        operation_date=date(2026, 9, 2),
        created_at=datetime(2026, 9, 2, 10, 0),
        item_id=1,
        location_id=1,
        type="consume",
        quantity=Decimal("4.000"),
        doc_number="CONS-2",
        allocations=(
            AllocationSnapshot(
                id=10,
                movement_id=2,
                batch_id=1,
                quantity=Decimal("4.000"),
                unit_price=Decimal("100.00"),
            ),
        ),
    )

    # Пытаемся переместить приход на объект 2 при наличии расхода cons на объекте 1
    op = AmendmentOperation(
        movement_id=1,
        action="update",
        location_id=2,
    )
    res = simulate_amendment_set(
        batches=[b],
        movements=[rec, cons],
        operations=[op],
        today=date(2026, 9, 10),
    )

    assert not res.can_apply
    bl = next(b for b in res.blockers if b.code == "DEPENDENT_OPERATIONS_ON_OLD_LOCATION")
    assert bl.movement_id == 1
    assert bl.batch_id == 1
