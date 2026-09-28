"""Интеграционные тесты согласованного снимка БД: REPEATABLE READ, фильтры и порядок."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.models.catalog import Item, Location, Supplier
from app.models.procurement import PurchaseOrder
from app.procurement_plan.repository import (
    load_catalog_pairs,
    load_plan_database_snapshot,
    set_repeatable_read_snapshot,
)
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_receipt_record,
    make_supplier_condition,
)


@pytest.fixture
def catalog_fixtures(db_session: Session) -> dict[str, list]:
    """Тестовые справочники с несколькими товарами, категориями и объектами."""
    loc_msk = Location(code="LOC-MSK", name="Москва SPA")
    loc_spb = Location(code="LOC-SPB", name="СПб SPA")
    db_session.add_all([loc_msk, loc_spb])

    sup1 = Supplier(supplier_id="SUP-01", name="Поставщик 1")
    sup2 = Supplier(supplier_id="SUP-02", name="Поставщик 2")
    db_session.add_all([sup1, sup2])

    it_oil1 = Item(sku="SKU-OIL-1", name="Масло Арганы", category="Масла", unit="л")
    it_oil2 = Item(sku="SKU-OIL-2", name="Масло Жожоба", category="Масла", unit="л")
    it_crm1 = Item(sku="SKU-CRM-1", name="Крем для лица", category="Кремы", unit="шт")
    db_session.add_all([it_oil1, it_oil2, it_crm1])
    db_session.commit()

    return {
        "locations": [loc_msk, loc_spb],
        "suppliers": [sup1, sup2],
        "items": [it_oil1, it_oil2, it_crm1],
    }


def test_repeatable_read_snapshot_isolation(db_session: Session) -> None:
    """Проверка перевода транзакции сессии в уровень изоляции REPEATABLE READ."""
    set_repeatable_read_snapshot(db_session)
    isolation = db_session.execute(text("SHOW transaction_isolation")).scalar()
    assert isolation is not None
    assert isolation.lower() == "repeatable read"


def test_repeatable_read_snapshot_concurrent_modifications(
    db_session: Session,
    catalog_fixtures: dict[str, list],
) -> None:
    """Проверка изоляции снимка: транзакция не видит INSERT/UPDATE параллельной сессии."""
    as_of = date(2026, 9, 20)
    it_oil1 = catalog_fixtures["items"][0]
    loc_msk = catalog_fixtures["locations"][0]
    sup1 = catalog_fixtures["suppliers"][0]

    # Начальный существующий заказ
    make_purchase_order(
        db_session,
        it_oil1.id,
        loc_msk.id,
        sup1.id,
        doc_number="PO-SNAP-ORIGINAL",
        expected_date=date(2026, 9, 25),
        expected_qty=Decimal("10.000"),
        pending_qty=Decimal("10.000"),
    )

    factory = get_session_factory()

    # 1. Сессия снимка: открывает транзакцию REPEATABLE READ и делает первую выборку
    snapshot_session = factory()
    try:
        set_repeatable_read_snapshot(snapshot_session)
        snap1 = load_plan_database_snapshot(snapshot_session, as_of=as_of)
        assert len(snap1.pairs) == 6
        assert len(snap1.existing_orders) == 1
        assert snap1.existing_orders[0].doc_number == "PO-SNAP-ORIGINAL"
        assert snap1.existing_orders[0].pending_qty == Decimal("10.000")

        # 2. Параллельная сессия: делает INSERT нового товара/заказа и UPDATE существующего
        writer_session = factory()
        try:
            new_item = Item(
                sku="SKU-CONCURRENT-NEW",
                name="Новый крем",
                category="Кремы",
                unit="шт",
            )
            writer_session.add(new_item)
            writer_session.flush()

            make_purchase_order(
                writer_session,
                new_item.id,
                loc_msk.id,
                sup1.id,
                doc_number="PO-CONCURRENT-NEW",
                expected_date=date(2026, 9, 28),
                expected_qty=Decimal("5.000"),
                pending_qty=Decimal("5.000"),
            )

            po_to_update = (
                writer_session.query(PurchaseOrder)
                .filter(PurchaseOrder.doc_number == "PO-SNAP-ORIGINAL")
                .first()
            )
            assert po_to_update is not None
            po_to_update.pending_qty = Decimal("2.000")
            writer_session.commit()
        finally:
            writer_session.close()

        # 3. Сессия снимка повторяет выборку: изменения параллельной сессии НЕ видны
        snap2 = load_plan_database_snapshot(snapshot_session, as_of=as_of)

        # Защита от фантомов: число пар и заказов не изменилось
        assert len(snap2.pairs) == 6
        assert len(snap2.existing_orders) == 1
        assert not any(p.item.sku == "SKU-CONCURRENT-NEW" for p in snap2.pairs)
        assert not any(o.doc_number == "PO-CONCURRENT-NEW" for o in snap2.existing_orders)

        # Повторяемость чтения: pending_qty остаётся 10.000, а не 2.000
        po_snap2 = snap2.existing_orders[0]
        assert po_snap2.doc_number == "PO-SNAP-ORIGINAL"
        assert po_snap2.pending_qty == Decimal("10.000")
    finally:
        snapshot_session.close()

    # 4. Проверяющая новая сессия: видит зафиксированные изменения
    verifier_session = factory()
    try:
        snap3 = load_plan_database_snapshot(verifier_session, as_of=as_of)
        assert len(snap3.pairs) == 8  # 4 товара * 2 объекта
        assert len(snap3.existing_orders) == 2
        assert any(p.item.sku == "SKU-CONCURRENT-NEW" for p in snap3.pairs)
        assert any(o.doc_number == "PO-CONCURRENT-NEW" for o in snap3.existing_orders)

        po_snap3 = next(o for o in snap3.existing_orders if o.doc_number == "PO-SNAP-ORIGINAL")
        assert po_snap3.pending_qty == Decimal("2.000")
    finally:
        verifier_session.close()


def test_load_catalog_pairs_filters_and_order(
    db_session: Session,
    catalog_fixtures: dict[str, list],
) -> None:
    """Проверка детерминированного порядка (объект, категория, SKU) и фильтров."""
    # 1. Без фильтров: декартово произведение (2 объекта * 3 товара = 6 пар)
    pairs_all = load_catalog_pairs(db_session)
    assert len(pairs_all) == 6

    expected_order = [
        ("LOC-MSK", "Кремы", "SKU-CRM-1"),
        ("LOC-MSK", "Масла", "SKU-OIL-1"),
        ("LOC-MSK", "Масла", "SKU-OIL-2"),
        ("LOC-SPB", "Кремы", "SKU-CRM-1"),
        ("LOC-SPB", "Масла", "SKU-OIL-1"),
        ("LOC-SPB", "Масла", "SKU-OIL-2"),
    ]
    actual_order = [(loc.code, it.category, it.sku) for it, loc in pairs_all]
    assert actual_order == expected_order

    # 2. Фильтр по объекту LOC-SPB
    pairs_spb = load_catalog_pairs(db_session, location_code="LOC-SPB")
    assert len(pairs_spb) == 3
    assert all(loc.code == "LOC-SPB" for _, loc in pairs_spb)
    assert [it.sku for it, _ in pairs_spb] == ["SKU-CRM-1", "SKU-OIL-1", "SKU-OIL-2"]

    # 3. Фильтр по категории Масла
    pairs_oils = load_catalog_pairs(db_session, category="Масла")
    assert len(pairs_oils) == 4
    assert all(it.category == "Масла" for it, _ in pairs_oils)
    assert [loc.code for _, loc in pairs_oils] == ["LOC-MSK", "LOC-MSK", "LOC-SPB", "LOC-SPB"]

    # 4. Фильтр по объекту и категории
    pairs_single = load_catalog_pairs(db_session, location_code="LOC-MSK", category="Кремы")
    assert len(pairs_single) == 1
    assert pairs_single[0][0].sku == "SKU-CRM-1"
    assert pairs_single[0][1].code == "LOC-MSK"


def test_load_snapshot_procurement_conditions_and_fefo_history(
    db_session: Session,
    catalog_fixtures: dict[str, list],
) -> None:
    """Проверка корректной загрузки закупочных условий, цен и FEFO-партий."""
    it_oil1 = catalog_fixtures["items"][0]
    it_oil2 = catalog_fixtures["items"][1]
    loc_msk = catalog_fixtures["locations"][0]
    sup1 = catalog_fixtures["suppliers"][0]
    as_of = date(2026, 9, 20)

    make_supplier_condition(
        db_session,
        it_oil1.id,
        sup1.id,
        lead_time_days=7,
        package_size=Decimal("2.000"),
        min_order_qty=Decimal("10.000"),
        estimated_price=Decimal("150.00"),
    )
    make_receipt_record(
        db_session,
        it_oil1.id,
        loc_msk.id,
        operation_date=date(2026, 9, 15),
        unit_price=Decimal("145.50"),
        quantity=Decimal("20.000"),
        supplier_id=sup1.id,
    )

    make_supplier_condition(
        db_session,
        it_oil2.id,
        sup1.id,
        lead_time_days=10,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("5.000"),
        estimated_price=Decimal("220.00"),
    )

    snapshot = load_plan_database_snapshot(
        session=db_session,
        as_of=as_of,
        location_code=loc_msk.code,
        category="Масла",
    )

    assert len(snapshot.pairs) == 2
    p1 = next(p for p in snapshot.pairs if p.item.sku == "SKU-OIL-1")
    assert p1.procurement_context.lead_time_days == 7
    assert p1.procurement_context.package_size == Decimal("2.000")
    assert p1.procurement_context.min_order_qty == Decimal("10.000")
    assert p1.procurement_context.unit_price == Decimal("145.50")
    assert p1.procurement_context.price_source == "receipt"
    assert len(p1.batches) == 1
    assert len(p1.movements) == 1

    p2 = next(p for p in snapshot.pairs if p.item.sku == "SKU-OIL-2")
    assert p2.procurement_context.unit_price == Decimal("220.00")
    assert p2.procurement_context.price_source == "estimated"
    assert len(p2.batches) == 0
