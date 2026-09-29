"""Тесты структуры определений демонстрационного набора данных."""

from decimal import Decimal

from app.demo_data.catalog import (
    DEMO_CONDITIONS,
    DEMO_ITEMS,
    DEMO_LOCATIONS,
    DEMO_SKU_LOCATIONS,
    DEMO_SUPPLIERS,
)
from app.demo_data.movements import (
    DEMO_BASE_RECEIPT_DOC,
    DEMO_BASE_RECEIPT_OFFSET,
    DEMO_MOVEMENTS,
)


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
