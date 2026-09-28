"""Интеграционные тесты пакетной выборки снимка БД с постоянной сложностью O(1)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.database import get_engine, get_session_factory
from app.models.catalog import Item, Location, Supplier
from app.procurement_plan.repository import load_plan_database_snapshot
from tests.forecasting_fixtures import (
    make_purchase_order,
    make_receipt_record,
    make_supplier_condition,
)


@pytest.fixture
def batch_catalog_fixtures(db_session: Session) -> dict[str, list]:
    """Справочники с несколькими объектами и товарами для проверки O(1) запросов."""
    locs = [
        Location(code="LOC-B1", name="Объект 1"),
        Location(code="LOC-B2", name="Объект 2"),
        Location(code="LOC-B3", name="Объект 3"),
    ]
    db_session.add_all(locs)

    sups = [
        Supplier(supplier_id="SUP-B1", name="Поставщик 1"),
        Supplier(supplier_id="SUP-B2", name="Поставщик 2"),
    ]
    db_session.add_all(sups)

    items = [
        Item(sku=f"SKU-BATCH-{i:02d}", name=f"Товар {i}", category="Масла", unit="л")
        for i in range(1, 6)
    ]
    db_session.add_all(items)
    db_session.commit()

    return {"locations": locs, "suppliers": sups, "items": items}


def test_batch_snapshot_fixed_query_count_o1(
    db_session: Session,
    batch_catalog_fixtures: dict[str, list],
) -> None:
    """Проверка фиксированного числа запросов O(1) независимо от количества пар."""
    items = batch_catalog_fixtures["items"]
    locs = batch_catalog_fixtures["locations"]
    sup = batch_catalog_fixtures["suppliers"][0]
    as_of = date(2026, 9, 20)

    # Заполняем условия, движения и заказы для нескольких пар
    for it in items[:3]:
        make_supplier_condition(db_session, it.id, sup.id, estimated_price=Decimal("100.00"))
        make_receipt_record(
            db_session,
            it.id,
            locs[0].id,
            date(2026, 9, 10),
            Decimal("95.00"),
            doc_number=f"DOC-REC-{it.sku}",
            batch_number=f"B-REC-{it.sku}",
        )
        make_purchase_order(
            db_session,
            it.id,
            locs[0].id,
            sup.id,
            doc_number=f"PO-{it.sku}",
            expected_date=date(2026, 9, 25),
            expected_qty=Decimal("10.000"),
        )

    engine = get_engine()
    queries: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        # Выборка по 3 объектам * 5 товаров = 15 пар
        queries.clear()
        snapshot = load_plan_database_snapshot(db_session, as_of=as_of)
        assert len(snapshot.pairs) == 15
        query_count_15_pairs = len(queries)

        # Выборка по 1 объекту * 5 товаров = 5 пар
        factory = get_session_factory()
        s2 = factory()
        try:
            queries.clear()
            snapshot_single_loc = load_plan_database_snapshot(
                s2,
                as_of=as_of,
                location_code="LOC-B1",
            )
            assert len(snapshot_single_loc.pairs) == 5
            query_count_5_pairs = len(queries)
        finally:
            s2.close()

        # Число запросов должно быть строго фиксированным O(1) и не зависеть от числа пар (<= 8)
        assert query_count_15_pairs <= 8
        assert query_count_5_pairs <= 8
        assert query_count_15_pairs == query_count_5_pairs
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
