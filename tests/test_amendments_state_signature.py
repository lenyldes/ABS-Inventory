"""Тесты для задачи 3.1: загрузка затронутых пар, заказов, блокировка и подпись состояния."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.inventory.amendments_domain import AmendmentOperation
from app.inventory.amendments_signature import compute_state_signature
from app.inventory.amendments_state import (
    acquire_amendment_locks,
    find_affected_pairs_and_orders,
    load_amendment_state,
)
from app.inventory.exceptions import EntityNotFoundError
from app.inventory.operations import register_consume, register_receipt
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement
from app.models.procurement import PurchaseOrder


def _setup_entities(session: Session) -> tuple[Item, Location, Batch, Movement]:
    """Создаёт базовые тестовые сущности: товар, объект, партию и приход."""
    item = Item(sku="OIL-SIG-01", name="Масло жожоба", category="Масла", unit="л")
    loc = Location(code="LOC-SIG-01", name="SPA Центр")
    session.add_all([item, loc])
    session.commit()

    rec_res = register_receipt(
        session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("10.000"),
        doc_number="REC-SIG-01",
        batch_number="B-SIG-01",
        expiry_date=date(2027, 9, 20),
        unit_price=Decimal("150.00"),
    )
    session.commit()
    rec = rec_res.movement
    batch = session.get(Batch, rec.batch_id)
    assert batch is not None
    return item, loc, batch, rec


def test_signature_deterministic_and_sensitive_to_changes() -> None:
    """Подпись детерминирована и изменяется при любых существенных модификациях состояния."""
    m1 = Movement(
        id=1,
        operation_date=date(2026, 9, 1),
        type="receipt",
        quantity=Decimal("10.000"),
        doc_number="DOC-1",
        status="active",
        current_version=1,
    )
    b1 = Batch(
        id=1,
        batch_number="B-1",
        receipt_date=date(2026, 9, 1),
        unit_price=Decimal("100.00"),
        receipt_doc_number="DOC-1",
        location_id=1,
    )
    po1 = PurchaseOrder(
        id=1,
        status="pending",
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("0.000"),
        pending_qty=Decimal("10.000"),
    )
    op1 = AmendmentOperation(movement_id=1, action="update", expected_version=1)

    sig1 = compute_state_signature([(1, 1)], [m1], [b1], [po1], [op1])
    sig1_repeat = compute_state_signature([(1, 1)], [m1], [b1], [po1], [op1])
    assert sig1 == sig1_repeat
    assert sig1.startswith("sig_")

    # Добавление нового движения в пару меняет подпись
    m2 = Movement(
        id=2,
        operation_date=date(2026, 9, 2),
        type="consume",
        quantity=Decimal("2.000"),
        doc_number="DOC-2",
        status="active",
        current_version=1,
    )
    sig_new_movement = compute_state_signature([(1, 1)], [m1, m2], [b1], [po1], [op1])
    assert sig_new_movement != sig1

    # Изменение версии операции меняет подпись
    op1_v2 = AmendmentOperation(movement_id=1, action="update", expected_version=2)
    sig_version_change = compute_state_signature([(1, 1)], [m1], [b1], [po1], [op1_v2])
    assert sig_version_change != sig1

    # Изменение заказа меняет подпись
    po1_updated = PurchaseOrder(
        id=1,
        status="received",
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("10.000"),
        pending_qty=Decimal("0.000"),
    )
    sig_po_change = compute_state_signature([(1, 1)], [m1], [b1], [po1_updated], [op1])
    assert sig_po_change != sig1


def test_find_affected_pairs_and_orders(db_session: Session) -> None:
    """Определение затронутых пар и заказов учитывает смену локации и партий."""
    item, loc, _, rec = _setup_entities(db_session)
    loc2 = Location(code="LOC-SIG-02", name="SPA Юг")
    db_session.add(loc2)
    db_session.commit()

    # Операция без смены локации
    op_same = AmendmentOperation(movement_id=rec.id, action="update")
    pairs, pos = find_affected_pairs_and_orders(db_session, [op_same])
    assert pairs == [(item.id, loc.id)]
    assert pos == []

    # Операция со сменой локации
    op_move = AmendmentOperation(
        movement_id=rec.id,
        action="update",
        location_code=loc2.code,
    )
    pairs_move, _ = find_affected_pairs_and_orders(db_session, [op_move])
    assert pairs_move == sorted([(item.id, loc.id), (item.id, loc2.id)])

    # Несуществующее движение
    with pytest.raises(EntityNotFoundError):
        find_affected_pairs_and_orders(
            db_session,
            [AmendmentOperation(movement_id=999999, action="update")],
        )


def test_acquire_amendment_locks_orders(db_session: Session) -> None:
    """Блокировка пар и заказов работает корректно в транзакции."""
    item, loc, _, _ = _setup_entities(db_session)
    supp = Supplier(supplier_id="SUP-SIG-01", name="Поставщик")
    db_session.add(supp)
    db_session.flush()

    po = PurchaseOrder(
        item_id=item.id,
        location_id=loc.id,
        supplier_id=supp.id,
        doc_number="PO-SIG-01",
        expected_date=date(2026, 10, 1),
        expected_qty=Decimal("20.000"),
        received_qty=Decimal("0.000"),
        pending_qty=Decimal("20.000"),
        status="pending",
    )
    db_session.add(po)
    db_session.commit()

    locked_pos = acquire_amendment_locks(
        db_session,
        pairs=[(item.id, loc.id)],
        po_ids=[po.id],
    )
    assert len(locked_pos) == 1
    assert locked_pos[0].id == po.id


def test_concurrent_new_movement_detected_via_signature(db_session: Session) -> None:
    """Конкурентный тест: новое движение по паре изменяет подпись состояния."""
    item, loc, _, rec = _setup_entities(db_session)
    op = AmendmentOperation(movement_id=rec.id, action="update", expected_version=1)

    state_before = load_amendment_state(db_session, [op])
    sig_before = state_before.version_signature
    db_session.commit()

    # В параллельном потоке регистрируем новый расход по той же паре
    factory = get_session_factory()

    def concurrent_consume() -> None:
        session = factory()
        try:
            with session.begin():
                it = session.get(Item, item.id)
                lc = session.get(Location, loc.id)
                assert it is not None and lc is not None
                register_consume(
                    session,
                    item=it,
                    location=lc,
                    operation_date=date(2026, 9, 21),
                    quantity=Decimal("1.000"),
                    doc_number="CONS-SIG-01",
                )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(concurrent_consume)
        future.result()

    # Перечитываем состояние в новой сессии
    state_after = load_amendment_state(db_session, [op])
    sig_after = state_after.version_signature
    db_session.commit()

    # Новое движение по паре обнаружено: подпись изменилась!
    assert sig_before != sig_after
    assert len(state_after.movements) == len(state_before.movements) + 1
