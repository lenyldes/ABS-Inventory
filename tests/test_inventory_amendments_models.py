"""Тесты ORM-моделей партий, движений, распределений, аудита и блокировок."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.amendments import AmendmentEntry, AmendmentSet, MovementVersion
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation, StockLock


@pytest.fixture
def base_catalog(db_session: Session) -> tuple[Item, Location, Supplier]:
    """Базовые товар, объект и поставщик для создания движений."""
    item = Item(sku="OIL-INV-01", name="Масло массажное", category="Масла", unit="л")
    loc = Location(code="LOC-01", name="SPA Центр")
    sup = Supplier(supplier_id="SUP-INV-01", name="АромаОпт")
    db_session.add_all([item, loc, sup])
    db_session.commit()
    return item, loc, sup


def test_batch_creation_and_precision(
    db_session: Session, base_catalog: tuple[Item, Location, Supplier]
) -> None:
    """Проверяет создание партии, точность цены и внешние ключи."""
    item, loc, _ = base_catalog

    batch = Batch(
        item_id=item.id,
        location_id=loc.id,
        batch_number="B-2026-001",
        receipt_date=date(2026, 9, 20),
        expiry_date=date(2027, 3, 20),
        unit_price=Decimal("450.50"),
        receipt_doc_number="DOC-REC-01",
    )
    db_session.add(batch)
    db_session.commit()

    saved_batch = db_session.get(Batch, batch.id)
    assert saved_batch is not None
    assert saved_batch.item.sku == "OIL-INV-01"
    assert saved_batch.location.code == "LOC-01"
    assert saved_batch.unit_price == Decimal("450.50")
    assert saved_batch.expiry_date == date(2027, 3, 20)

    # Отрицательная цена запрещена
    bad_batch = Batch(
        item_id=item.id,
        location_id=loc.id,
        batch_number="B-BAD-01",
        receipt_date=date(2026, 9, 20),
        unit_price=Decimal("-10.00"),
        receipt_doc_number="DOC-REC-BAD",
    )
    db_session.add(bad_batch)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_movement_partial_unique_doc_number_and_reuse_on_cancel(
    db_session: Session, base_catalog: tuple[Item, Location, Supplier]
) -> None:
    """Проверяет частичную уникальность активного doc_number и его освобождение при отмене."""
    item, loc, _ = base_catalog

    m1 = Movement(
        operation_date=date(2026, 9, 28),
        item_id=item.id,
        location_id=loc.id,
        type="consume",
        quantity=Decimal("5.000"),
        doc_number="DOC-ACT-001",
        status="active",
    )
    db_session.add(m1)
    db_session.commit()

    # Попытка создать второе активное движение с тем же номером на том же объекте запрещена
    m_dup = Movement(
        operation_date=date(2026, 9, 28),
        item_id=item.id,
        location_id=loc.id,
        type="consume",
        quantity=Decimal("3.000"),
        doc_number="DOC-ACT-001",
        status="active",
    )
    db_session.add(m_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Отменяем первое движение: статус меняется на 'cancelled'
    m1_db = db_session.get(Movement, m1.id)
    assert m1_db is not None
    m1_db.status = "cancelled"
    db_session.commit()

    # Теперь новый документ с тем же номером на этом же объекте успешно создаётся
    m2_reuse = Movement(
        operation_date=date(2026, 9, 28),
        item_id=item.id,
        location_id=loc.id,
        type="consume",
        quantity=Decimal("4.000"),
        doc_number="DOC-ACT-001",
        status="active",
    )
    db_session.add(m2_reuse)
    db_session.commit()
    assert m2_reuse.id is not None
    assert m2_reuse.id != m1.id


def test_movement_and_allocation_precision(
    db_session: Session, base_catalog: tuple[Item, Location, Supplier]
) -> None:
    """Проверяет точность количества и распределение расхода по партиям."""
    item, loc, _ = base_catalog

    batch = Batch(
        item_id=item.id,
        location_id=loc.id,
        batch_number="B-2026-002",
        receipt_date=date(2026, 9, 1),
        expiry_date=date(2026, 12, 1),
        unit_price=Decimal("100.25"),
        receipt_doc_number="DOC-REC-02",
    )
    db_session.add(batch)
    db_session.commit()

    mov = Movement(
        operation_date=date(2026, 9, 28),
        item_id=item.id,
        location_id=loc.id,
        type="consume",
        quantity=Decimal("0.125"),
        doc_number="DOC-ALLOC-01",
    )
    db_session.add(mov)
    db_session.commit()

    alloc = MovementAllocation(
        movement_id=mov.id,
        batch_id=batch.id,
        quantity=Decimal("0.125"),
        unit_price=Decimal("100.25"),
    )
    db_session.add(alloc)
    db_session.commit()

    saved_alloc = db_session.get(MovementAllocation, alloc.id)
    assert saved_alloc is not None
    assert saved_alloc.quantity == Decimal("0.125")
    assert saved_alloc.unit_price == Decimal("100.25")
    assert saved_alloc.movement.doc_number == "DOC-ALLOC-01"
    assert saved_alloc.batch.batch_number == "B-2026-002"


def test_stock_lock_uniqueness(
    db_session: Session, base_catalog: tuple[Item, Location, Supplier]
) -> None:
    """Проверяет уникальность пары (товар, объект) в stock_locks."""
    item, loc, _ = base_catalog

    lock1 = StockLock(item_id=item.id, location_id=loc.id)
    db_session.add(lock1)
    db_session.commit()

    assert lock1.id is not None

    # Повторная блокировка той же пары вызывает IntegrityError
    lock_dup = StockLock(item_id=item.id, location_id=loc.id)
    db_session.add(lock_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_amendments_and_versions(
    db_session: Session, base_catalog: tuple[Item, Location, Supplier]
) -> None:
    """Проверяет набор исправлений, каскадное удаление строк и аудит версий."""
    item, loc, _ = base_catalog

    mov = Movement(
        operation_date=date(2026, 9, 28),
        item_id=item.id,
        location_id=loc.id,
        type="receipt",
        quantity=Decimal("20.000"),
        doc_number="DOC-REC-AMEND",
    )
    db_session.add(mov)
    db_session.commit()

    # Аудит версии 1
    v1 = MovementVersion(
        movement_id=mov.id,
        version_num=1,
        action="create",
        reason="Первичный ввод",
        snapshot={"quantity": "20.000", "doc_number": "DOC-REC-AMEND"},
    )
    db_session.add(v1)
    db_session.commit()

    # Дубликат версии для того же движения запрещён
    v1_dup = MovementVersion(
        movement_id=mov.id,
        version_num=1,
        action="update",
        reason="Попытка перезаписи",
        snapshot={},
    )
    db_session.add(v1_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Набор исправлений и строка операции
    amend_set = AmendmentSet(
        amendment_id="amend-20260928-001",
        reason="Опечатка оператора при приёмке",
        status="preview",
        version_signature="sig_test_12345",
        preview_data={"stock_impact": [{"sku": item.sku, "diff": "-18.000"}]},
    )
    db_session.add(amend_set)
    db_session.commit()

    entry = AmendmentEntry(
        amendment_set_id=amend_set.id,
        movement_id=mov.id,
        action="update",
        expected_version=1,
        details={"quantity": "2.000"},
    )
    db_session.add(entry)
    db_session.commit()

    # Проверяем связь и каскадное удаление
    saved_set = db_session.get(AmendmentSet, amend_set.id)
    assert saved_set is not None
    assert len(saved_set.entries) == 1
    assert saved_set.entries[0].details == {"quantity": "2.000"}

    # Удаление набора каскадно удаляет его строки (entries), но не само движение
    db_session.delete(saved_set)
    db_session.commit()

    assert db_session.get(AmendmentEntry, entry.id) is None
    assert db_session.get(Movement, mov.id) is not None
