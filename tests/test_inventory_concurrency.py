"""Интеграционные тесты сериализации транзакций склада через stock_locks на PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.inventory.exceptions import InsufficientStockError
from app.inventory.operations import (
    register_consume,
    register_receipt,
)
from app.models.catalog import Item, Location


def test_concurrent_consumes_cannot_overdraw_stock(
    db_session: Session,
) -> None:
    """Два конкурентных расхода не могут оба списать общий недостаточный остаток."""
    item = Item(sku="OIL-CONC-01", name="Масло кокосовое", category="Масла", unit="л")
    loc = Location(code="LOC-CONC-01", name="SPA Север")
    db_session.add_all([item, loc])
    db_session.commit()

    # Начальный приход 5.000 литров
    register_receipt(
        db_session,
        item=item,
        location=loc,
        operation_date=date(2026, 9, 20),
        quantity=Decimal("5.000"),
        doc_number="REC-INIT-01",
        batch_number="B-INIT",
        expiry_date=date(2027, 3, 20),
        unit_price=Decimal("300.00"),
    )
    db_session.commit()

    item_id = item.id
    location_id = loc.id

    factory = get_session_factory()
    results: list[str] = []

    def try_consume(doc_num: str) -> None:
        session = factory()
        try:
            with session.begin():
                item_db = session.get(Item, item_id)
                loc_db = session.get(Location, location_id)
                assert item_db is not None and loc_db is not None
                register_consume(
                    session,
                    item=item_db,
                    location=loc_db,
                    operation_date=date(2026, 9, 21),
                    quantity=Decimal("4.000"),
                    doc_number=doc_num,
                )
            results.append("success")
        except InsufficientStockError:
            results.append("insufficient_stock")
        finally:
            session.close()

    # Запускаем два одновременных расхода по 4 литра при доступных 5 литрах
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_consume, "CONS-CONC-A")
        f2 = executor.submit(try_consume, "CONS-CONC-B")
        f1.result()
        f2.result()

    # Ровно один должен завершиться успехом, второй - отказом
    assert sorted(results) == ["insufficient_stock", "success"]
