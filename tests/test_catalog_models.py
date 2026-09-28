"""Тесты ORM-моделей справочников каталога (Item, Location, Supplier)."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import Item, Location, Supplier
from app.models.procurement import SupplierCondition


def test_item_creation_and_unique_sku(db_session: Session) -> None:
    """Проверяет создание товара и уникальность SKU."""
    item1 = Item(sku="OIL-001", name="Масло жожоба", category="Масла", unit="л")
    db_session.add(item1)
    db_session.commit()

    assert item1.id is not None
    assert item1.sku == "OIL-001"

    # Попытка создать дубликат SKU вызывает IntegrityError
    item_dup = Item(sku="OIL-001", name="Другое масло", category="Масла", unit="л")
    db_session.add(item_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_location_creation_and_unique_code(db_session: Session) -> None:
    """Проверяет создание объекта и уникальность кода."""
    loc1 = Location(code="MSK-01", name="SPA Арбат")
    db_session.add(loc1)
    db_session.commit()

    assert loc1.id is not None

    loc_dup = Location(code="MSK-01", name="SPA Тверская")
    db_session.add(loc_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_supplier_creation_and_unique_id(db_session: Session) -> None:
    """Проверяет создание поставщика и уникальность supplier_id."""
    sup1 = Supplier(supplier_id="SUP-01", name="АромаЛюкс")
    db_session.add(sup1)
    db_session.commit()

    assert sup1.id is not None

    sup_dup = Supplier(supplier_id="SUP-01", name="Другой поставщик")
    db_session.add(sup_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_delete_with_linked_records(db_session: Session) -> None:
    """Проверяет RESTRICT при удалении сущностей со связанными условиями."""
    item = Item(sku="SOAP-01", name="Мыло ручной работы", category="Мыло", unit="шт")
    sup = Supplier(supplier_id="SUP-08", name="Мыловарня")
    db_session.add_all([item, sup])
    db_session.commit()

    cond = SupplierCondition(
        item_id=item.id,
        supplier_id=sup.id,
        lead_time_days=3,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("10.000"),
    )
    db_session.add(cond)
    db_session.commit()

    # Попытка удалить поставщика через SQL напрямую блокируется RESTRICT
    with pytest.raises(IntegrityError):
        db_session.delete(sup)
        db_session.commit()
    db_session.rollback()
