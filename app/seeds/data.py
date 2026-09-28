"""Детерминированный набор начальных данных (сидов) для этапа 05.

Включает базовые объекты (SPA-филиалы), поставщиков, товары и закупочные условия.
Не содержит партий и движений (они относятся к этапу 06).
"""

from decimal import Decimal

SEED_LOCATIONS = [
    {
        "code": "MS-01",
        "name": "Mountain & Sea Spa — Москва-Центр",
    },
    {
        "code": "MS-02",
        "name": "Mountain & Sea Spa — Сочи-Поляна",
    },
]

SEED_SUPPLIERS = [
    {
        "supplier_id": "SUP-AROMA",
        "name": "Арома-Трейд ООО",
    },
    {
        "supplier_id": "SUP-BEAUTY",
        "name": "Бьюти Косметикс АО",
    },
]

SEED_ITEMS = [
    {
        "sku": "OIL-001",
        "name": "Массажное масло базовое (миндаль)",
        "category": "Масла и косметика",
        "unit": "л",
    },
    {
        "sku": "SCRUB-001",
        "name": "Скраб для тела солевой (лаванда)",
        "category": "Косметика для тела",
        "unit": "кг",
    },
    {
        "sku": "SHEET-001",
        "name": "Простыни одноразовые в рулоне",
        "category": "Расходные материалы",
        "unit": "шт",
    },
]

SEED_CONDITIONS = [
    {
        "item_sku": "OIL-001",
        "supplier_id": "SUP-AROMA",
        "lead_time_days": 7,
        "package_size": Decimal("5.000"),
        "min_order_qty": Decimal("10.000"),
        "estimated_price": Decimal("1250.00"),
        "is_primary": True,
    },
    {
        "item_sku": "OIL-001",
        "supplier_id": "SUP-BEAUTY",
        "lead_time_days": 14,
        "package_size": Decimal("1.000"),
        "min_order_qty": Decimal("5.000"),
        "estimated_price": Decimal("1400.00"),
        "is_primary": False,
    },
    {
        "item_sku": "SCRUB-001",
        "supplier_id": "SUP-BEAUTY",
        "lead_time_days": 10,
        "package_size": Decimal("2.000"),
        "min_order_qty": Decimal("6.000"),
        "estimated_price": Decimal("850.00"),
        "is_primary": True,
    },
    {
        "item_sku": "SHEET-001",
        "supplier_id": "SUP-AROMA",
        "lead_time_days": 5,
        "package_size": Decimal("10.000"),
        "min_order_qty": Decimal("10.000"),
        "estimated_price": Decimal("350.00"),
        "is_primary": True,
    },
]

SEED_MOVEMENTS = [
    {
        "doc_number": "SEED-REC-001",
        "sku": "OIL-001",
        "location": "MS-01",
        "type": "receipt",
        "quantity": Decimal("20.000"),
        "batch_number": "SEED-BATCH-OIL-01",
        "days_ago": 5,
        "expiry_days_ahead": 180,
        "unit_price": Decimal("1250.00"),
        "supplier_id": "SUP-AROMA",
    },
    {
        "doc_number": "SEED-CONS-001",
        "sku": "OIL-001",
        "location": "MS-01",
        "type": "consume",
        "quantity": Decimal("4.000"),
        "days_ago": 2,
    },
    {
        "doc_number": "SEED-REC-002",
        "sku": "SCRUB-001",
        "location": "MS-01",
        "type": "receipt",
        "quantity": Decimal("15.000"),
        "batch_number": "SEED-BATCH-SCRUB-01",
        "days_ago": 4,
        "expiry_days_ahead": 90,
        "unit_price": Decimal("850.00"),
        "supplier_id": "SUP-BEAUTY",
    },
]
