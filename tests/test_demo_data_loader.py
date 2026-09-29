"""Тесты структуры определений и загрузки демонстрационного набора данных."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.demo_data.catalog import (
    DEMO_CONDITIONS,
    DEMO_ITEMS,
    DEMO_LOCATIONS,
    DEMO_SKU_LOCATIONS,
    DEMO_SUPPLIERS,
)
from app.demo_data.loader import load_demo_data
from app.demo_data.movements import (
    DEMO_BASE_RECEIPT_DOC,
    DEMO_BASE_RECEIPT_OFFSET,
    DEMO_MOVEMENTS,
)
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import (
    Batch,
    Movement,
    MovementAllocation,
)
from app.models.procurement import PurchaseOrder, SupplierCondition

TEST_AS_OF = date(2026, 9, 29)


def test_demo_definitions_composition() -> None:
    """Проверяет полноту объектов, поставщиков, SKU и категорий (задача 1.1)."""
    # 1. Объекты: ровно 2, коды начинаются с DEMO-
    assert len(DEMO_LOCATIONS) == 2
    loc_codes = {loc["code"] for loc in DEMO_LOCATIONS}
    assert loc_codes == {"DEMO-MS-01", "DEMO-MS-02"}
    assert all(c.startswith("DEMO-") for c in loc_codes)

    # 2. Поставщики: ровно 2, начинаются с DEMO-
    assert len(DEMO_SUPPLIERS) == 2
    sup_ids = {s["supplier_id"] for s in DEMO_SUPPLIERS}
    assert sup_ids == {"DEMO-SUP-MAIN", "DEMO-SUP-ALT"}

    # 3. Девять ситуаций и SKU, префикс DEMO-
    assert len(DEMO_ITEMS) == 9
    expected_skus = {
        "DEMO-OIL",
        "DEMO-DEFICIT",
        "DEMO-EXPIRY",
        "DEMO-EXPIRED",
        "DEMO-IDLE",
        "DEMO-SHORT",
        "DEMO-NOPRICE",
        "DEMO-NOLEAD",
        "DEMO-INCOMING",
    }
    actual_skus = {item["sku"] for item in DEMO_ITEMS}
    assert actual_skus == expected_skus
    assert all(sku.startswith("DEMO-") for sku in actual_skus)

    # 4. Минимум три категории
    categories = {item["category"] for item in DEMO_ITEMS}
    assert len(categories) >= 3

    # 5. Размещение по объектам: DEMO-DEFICIT и DEMO-SHORT на DEMO-MS-02, остальные на DEMO-MS-01
    assert DEMO_SKU_LOCATIONS["DEMO-DEFICIT"] == "DEMO-MS-02"
    assert DEMO_SKU_LOCATIONS["DEMO-SHORT"] == "DEMO-MS-02"
    for sku, loc in DEMO_SKU_LOCATIONS.items():
        if sku not in {"DEMO-DEFICIT", "DEMO-SHORT"}:
            assert loc == "DEMO-MS-01"

    # 6. Закупочные условия: для DEMO-NOLEAD условий нет, для DEMO-NOPRICE цена None
    cond_skus = {c["item_sku"] for c in DEMO_CONDITIONS}
    assert "DEMO-NOLEAD" not in cond_skus
    assert "DEMO-NOPRICE" in cond_skus
    noprice_cond = next(c for c in DEMO_CONDITIONS if c["item_sku"] == "DEMO-NOPRICE")
    assert noprice_cond["estimated_price"] is None
    assert noprice_cond["is_primary"] is True


def test_demo_definitions_history_and_oil() -> None:
    """Проверяет историю движений внутри и вне 90 дней, масло и расход 1/день (задача 1.1)."""
    # 1. Опорный приход масла
    base_m = next(m for m in DEMO_MOVEMENTS if m.doc_number == DEMO_BASE_RECEIPT_DOC)
    assert base_m.sku == "DEMO-OIL"
    assert base_m.movement_type == "receipt"
    assert base_m.offset_days == DEMO_BASE_RECEIPT_OFFSET == -100
    assert base_m.quantity == Decimal("140.000")
    assert base_m.batch_number == "DEMO-BATCH-OIL"

    # 2. Расходы масла: ровно 90 дней от -89 до 0 включительно
    oil_consumes = [
        m for m in DEMO_MOVEMENTS if m.sku == "DEMO-OIL" and m.movement_type == "consume"
    ]
    assert len(oil_consumes) == 90
    consume_offsets = [m.offset_days for m in oil_consumes]
    assert consume_offsets == list(range(-89, 1))
    assert all(m.quantity == Decimal("1.000") for m in oil_consumes)

    # 3. Расчетный остаток масла: 140 - 90 = 50, средний расход 90 / 90 = 1.000000
    total_consumed = sum(m.quantity for m in oil_consumes)
    assert total_consumed == Decimal("90.000")
    assert base_m.quantity - total_consumed == Decimal("50.000")
    avg_daily_consumption = total_consumed / Decimal(len(oil_consumes))
    assert avg_daily_consumption == Decimal("1.000000")

    # 4. Движения вне 90-дневного окна (< -89 дней)
    outside_window = [m for m in DEMO_MOVEMENTS if m.offset_days < -89]
    assert len(outside_window) >= 2  # Приходы на -100 и -120 дней
    outside_skus = {m.sku for m in outside_window}
    assert "DEMO-OIL" in outside_skus
    assert "DEMO-IDLE" in outside_skus

    # 5. Движения внутри 90-дневного окна (>= -89 дней)
    inside_window = [m for m in DEMO_MOVEMENTS if m.offset_days >= -89]
    assert len(inside_window) >= 90
    inside_skus = {m.sku for m in inside_window}
    assert "DEMO-SHORT" in inside_skus  # Приход на -10, расход на -5
    assert "DEMO-EXPIRY" in inside_skus  # Приход на -20, расход на -5


def test_load_demo_data_on_postgres(db_session: Session) -> None:
    """Проверяет загрузку на пустую PostgreSQL: остатки, FEFO, версии (задача 1.2)."""
    stats = load_demo_data(db_session, as_of=TEST_AS_OF)

    assert stats["locations"] == 2
    assert stats["suppliers"] == 2
    assert stats["items"] == 9
    assert stats["supplier_conditions"] == 8
    assert stats["movements"] == 105
    assert stats["batches"] == 9
    assert stats["orders"] == 1

    # Проверка остатков ключевых SKU
    # 1. Масло DEMO-OIL: приход 140, расход 90, остаток 50
    oil_batch = db_session.query(Batch).filter(Batch.batch_number == "DEMO-BATCH-OIL").one()
    alloc_sum = sum(
        a.quantity
        for a in db_session.query(MovementAllocation)
        .filter(MovementAllocation.batch_id == oil_batch.id)
        .all()
    )
    assert alloc_sum == Decimal("90.000")

    oil_item = db_session.query(Item).filter(Item.sku == "DEMO-OIL").one()
    receipts_total = sum(
        m.quantity
        for m in db_session.query(Movement)
        .filter(Movement.item_id == oil_item.id, Movement.type == "receipt")
        .all()
    )
    consumes_total = sum(
        m.quantity
        for m in db_session.query(Movement)
        .filter(Movement.item_id == oil_item.id, Movement.type == "consume")
        .all()
    )
    assert receipts_total - consumes_total == Decimal("50.000")

    # 2. DEMO-DEFICIT: остаток 5
    def_item = db_session.query(Item).filter(Item.sku == "DEMO-DEFICIT").one()
    def_m = db_session.query(Movement).filter(Movement.item_id == def_item.id).all()
    def_balance = sum(m.quantity if m.type == "receipt" else -m.quantity for m in def_m)
    assert def_balance == Decimal("5.000")

    # 3. FEFO-распределения: для каждого consume движения создано распределение
    consumes = db_session.query(Movement).filter(Movement.type == "consume").all()
    assert len(consumes) == 96
    for c in consumes:
        allocs = (
            db_session.query(MovementAllocation)
            .filter(MovementAllocation.movement_id == c.id)
            .all()
        )
        assert len(allocs) >= 1
        assert sum(a.quantity for a in allocs) == c.quantity

    # 4. Версии движений: для каждого движения создана запись версии через связь versions
    movements = db_session.query(Movement).all()
    assert len(movements) == 105
    for mv in movements:
        assert mv.current_version >= 1
        assert len(mv.versions) >= 1
        assert mv.versions[0].version_num == 1

    # 5. Ожидаемый заказ
    po = (
        db_session.query(PurchaseOrder).filter(PurchaseOrder.doc_number == "DEMO-PO-INCOMING").one()
    )
    assert po.status == "pending"
    assert po.expected_qty == Decimal("20.000")
    assert po.pending_qty == Decimal("20.000")
    assert po.received_qty == Decimal("0.000")


def test_load_demo_data_rollback_on_error(db_session: Session) -> None:
    """Проверяет полный откат транзакции при возникновении сбоя (задача 1.2)."""
    # Имитируем сбой во время проведения движений
    with patch(
        "app.demo_data.loader.register_consume",
        side_effect=RuntimeError("Simulated failure in register_consume"),
    ):
        with pytest.raises(RuntimeError, match="Simulated failure"):
            load_demo_data(db_session, as_of=TEST_AS_OF)

    # Проверяем, что в базе данных не осталось созданных записей
    assert db_session.query(Item).filter(Item.sku.like("DEMO-%")).count() == 0
    assert db_session.query(Location).filter(Location.code.like("DEMO-%")).count() == 0
    assert db_session.query(Supplier).filter(Supplier.supplier_id.like("DEMO-%")).count() == 0
    assert (
        db_session.query(SupplierCondition)
        .join(Item, SupplierCondition.item_id == Item.id)
        .filter(Item.sku.like("DEMO-%"))
        .count()
        == 0
    )
    assert db_session.query(Movement).filter(Movement.doc_number.like("DEMO-%")).count() == 0
    assert db_session.query(Batch).filter(Batch.batch_number.like("DEMO-%")).count() == 0
    assert (
        db_session.query(PurchaseOrder).filter(PurchaseOrder.doc_number.like("DEMO-%")).count() == 0
    )
