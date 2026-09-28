"""Вспомогательные фикстуры и генераторы данных для тестов предупреждений."""

from datetime import date, timedelta
from decimal import Decimal

from app.forecasting.domain import IncomingOrderSnapshot, ProcurementContext
from app.inventory.domain import BatchStock, MovementSnapshot, StockBalance

BASE_AS_OF = date(2026, 9, 28)


def make_test_balance(
    current_stock: Decimal = Decimal("10.000"),
    available_stock: Decimal = Decimal("10.000"),
    expired_stock: Decimal = Decimal("0.000"),
    batches: tuple[BatchStock, ...] = (),
) -> StockBalance:
    """Создаёт тестовый StockBalance."""
    return StockBalance(
        current_stock=current_stock,
        available_stock=available_stock,
        expired_stock=expired_stock,
        nearest_expiry_date=None,
        batches=batches,
    )


def make_test_batch_stock(
    batch_id: int = 1,
    batch_number: str = "B-01",
    receipt_date: date = date(2026, 9, 1),
    expiry_date: date | None = None,
    current_quantity: Decimal = Decimal("10.000"),
    available_quantity: Decimal = Decimal("10.000"),
    expired_quantity: Decimal = Decimal("0.000"),
) -> BatchStock:
    """Создаёт тестовый BatchStock."""
    return BatchStock(
        batch_id=batch_id,
        batch_number=batch_number,
        receipt_date=receipt_date,
        expiry_date=expiry_date,
        unit_price=Decimal("100.00"),
        receipt_doc_number="DOC-01",
        current_quantity=current_quantity,
        available_quantity=available_quantity,
        expired_quantity=expired_quantity,
    )


def make_test_procurement(
    lead_time_days: int | None = 5,
    pending_orders: tuple[IncomingOrderSnapshot, ...] = (),
    delayed_orders: tuple[IncomingOrderSnapshot, ...] = (),
) -> ProcurementContext:
    """Создаёт тестовый ProcurementContext."""
    return ProcurementContext(
        supplier_id="SUP-01",
        supplier_name="Тестовый поставщик",
        lead_time_days=lead_time_days,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("1.000"),
        unit_price=Decimal("100.00"),
        price_source="receipt",
        pending_orders=pending_orders,
        delayed_orders=delayed_orders,
    )


def make_test_movements(
    as_of: date = BASE_AS_OF,
    total_consume_90d: Decimal = Decimal("90.000"),
    history_days: int = 100,
) -> list[MovementSnapshot]:
    """Создаёт движения для формирования заданного потребления и длины истории."""
    movements = [
        MovementSnapshot(
            operation_date=as_of - timedelta(days=history_days),
            item_id=1,
            location_id=1,
            type="receipt",
            quantity=Decimal("1000.000"),
            doc_number="DOC-INIT",
            id=1,
            batch_id=1,
        )
    ]
    if total_consume_90d > Decimal("0"):
        movements.append(
            MovementSnapshot(
                operation_date=as_of - timedelta(days=10),
                item_id=1,
                location_id=1,
                type="consume",
                quantity=total_consume_90d,
                doc_number="DOC-CONS",
                id=2,
                batch_id=1,
            )
        )
    return movements
