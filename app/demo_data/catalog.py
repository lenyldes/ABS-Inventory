"""Определения каталога для демонстрационного набора данных."""

from decimal import Decimal
from typing import Any

# SPA-объекты
DEMO_LOCATIONS: list[dict[str, str]] = [
    {"code": "DEMO-MS-01", "name": "SPA Центр Север"},
    {"code": "DEMO-MS-02", "name": "SPA Центр Юг"},
]

# Поставщики
DEMO_SUPPLIERS: list[dict[str, str]] = [
    {"supplier_id": "DEMO-SUP-MAIN", "name": "Основной поставщик ДЕМО"},
    {"supplier_id": "DEMO-SUP-ALT", "name": "Запасной поставщик ДЕМО"},
]

# Номенклатура (9 SKU, минимум 3 категории)
DEMO_ITEMS: list[dict[str, str]] = [
    {
        "sku": "DEMO-OIL",
        "name": "Массажное масло Базовое 1л",
        "category": "Масла для массажа",
        "unit": "л",
    },
    {
        "sku": "DEMO-DEFICIT",
        "name": "Эфирное масло Лаванда 50мл",
        "category": "Косметика и уход",
        "unit": "шт",
    },
    {
        "sku": "DEMO-EXPIRY",
        "name": "Крем для тела Увлажняющий 250мл",
        "category": "Косметика и уход",
        "unit": "шт",
    },
    {
        "sku": "DEMO-EXPIRED",
        "name": "Скраб солевой Тонизирующий 500г",
        "category": "Косметика и уход",
        "unit": "шт",
    },
    {
        "sku": "DEMO-IDLE",
        "name": "Маска грязевая Восстанавливающая 1кг",
        "category": "Косметика и уход",
        "unit": "шт",
    },
    {
        "sku": "DEMO-SHORT",
        "name": "Лосьон после массажа 200мл",
        "category": "Косметика и уход",
        "unit": "шт",
    },
    {
        "sku": "DEMO-NOPRICE",
        "name": "Простыни одноразовые 70x200 100шт",
        "category": "Расходные материалы",
        "unit": "упак",
    },
    {
        "sku": "DEMO-NOLEAD",
        "name": "Шапочки одноразовые 100шт",
        "category": "Расходные материалы",
        "unit": "упак",
    },
    {
        "sku": "DEMO-INCOMING",
        "name": "Перчатки нитриловые M 100шт",
        "category": "Расходные материалы",
        "unit": "упак",
    },
]

# Привязка SKU к объектам: DEMO-DEFICIT и DEMO-SHORT на DEMO-MS-02, остальные на DEMO-MS-01
DEMO_SKU_LOCATIONS: dict[str, str] = {
    "DEMO-OIL": "DEMO-MS-01",
    "DEMO-DEFICIT": "DEMO-MS-02",
    "DEMO-EXPIRY": "DEMO-MS-01",
    "DEMO-EXPIRED": "DEMO-MS-01",
    "DEMO-IDLE": "DEMO-MS-01",
    "DEMO-SHORT": "DEMO-MS-02",
    "DEMO-NOPRICE": "DEMO-MS-01",
    "DEMO-NOLEAD": "DEMO-MS-01",
    "DEMO-INCOMING": "DEMO-MS-01",
}

# Закупочные условия (SupplierCondition)
# Для DEMO-NOLEAD условий нет вообще.
# Для DEMO-NOPRICE основное условие имеет estimated_price = None.
DEMO_CONDITIONS: list[dict[str, Any]] = [
    {
        "item_sku": "DEMO-OIL",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("5.000"),
        "min_order_qty": Decimal("10.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-DEFICIT",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 10,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-EXPIRY",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-EXPIRED",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-IDLE",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-SHORT",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-NOPRICE",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": None,
        "is_primary": True,
    },
    {
        "item_sku": "DEMO-INCOMING",
        "supplier_id": "DEMO-SUP-MAIN",
        "lead_time_days": 7,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("1.000"),
        "estimated_price": Decimal("100.00"),
        "is_primary": True,
    },
]

DEMO_LOCATION_CODES: set[str] = {loc["code"] for loc in DEMO_LOCATIONS}
DEMO_SUPPLIER_IDS: set[str] = {sup["supplier_id"] for sup in DEMO_SUPPLIERS}
DEMO_ITEM_SKUS: set[str] = {item["sku"] for item in DEMO_ITEMS}
