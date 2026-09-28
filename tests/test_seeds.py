"""Тесты начальных данных (сидов) и их идемпотентной загрузки."""

from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation
from app.models.procurement import PurchaseOrder, SupplierCondition
from app.seeds.data import (
    SEED_CONDITIONS,
    SEED_ITEMS,
    SEED_LOCATIONS,
    SEED_SUPPLIERS,
)
from app.seeds.loader import load_seeds, main


def test_seed_data_definitions_validity() -> None:
    """Проверка структуры и целостности исходных определений сидов."""
    assert len(SEED_LOCATIONS) >= 2
    assert len(SEED_SUPPLIERS) >= 2
    assert len(SEED_ITEMS) >= 3
    assert len(SEED_CONDITIONS) >= 4

    # Все SKU уникальны
    skus = [it["sku"] for it in SEED_ITEMS]
    assert len(skus) == len(set(skus))

    # Все коды объектов уникальны
    codes = [loc["code"] for loc in SEED_LOCATIONS]
    assert len(codes) == len(set(codes))

    # Все ID поставщиков уникальны
    sup_ids = [sup["supplier_id"] for sup in SEED_SUPPLIERS]
    assert len(sup_ids) == len(set(sup_ids))

    # Условия ссылаются только на существующие SKU и поставщиков
    for cond in SEED_CONDITIONS:
        assert cond["item_sku"] in skus
        assert cond["supplier_id"] in sup_ids
        assert cond["lead_time_days"] >= 1
        assert cond["package_size"] > 0
        assert cond["min_order_qty"] > 0


def test_load_seeds_first_run(db_session: Session) -> None:
    """Первый запуск: создание всех записей сидов и отсутствие движений."""
    stats = load_seeds(db_session)

    assert stats["locations"] == len(SEED_LOCATIONS)
    assert stats["suppliers"] == len(SEED_SUPPLIERS)
    assert stats["items"] == len(SEED_ITEMS)
    assert stats["supplier_conditions"] == len(SEED_CONDITIONS)

    # Проверка записей в базе данных
    assert db_session.query(func.count(Location.id)).scalar() == len(SEED_LOCATIONS)
    assert db_session.query(func.count(Supplier.id)).scalar() == len(SEED_SUPPLIERS)
    assert db_session.query(func.count(Item.id)).scalar() == len(SEED_ITEMS)
    assert db_session.query(func.count(SupplierCondition.id)).scalar() == len(SEED_CONDITIONS)

    # Строгое требование этапа 05: партии, движения и заказы отсутствуют
    assert db_session.query(func.count(Batch.id)).scalar() == 0
    assert db_session.query(func.count(Movement.id)).scalar() == 0
    assert db_session.query(func.count(MovementAllocation.id)).scalar() == 0
    assert db_session.query(func.count(PurchaseOrder.id)).scalar() == 0

    # Проверка конкретного товара и условий
    oil = db_session.query(Item).filter(Item.sku == "OIL-001").first()
    assert oil is not None
    assert oil.unit == "л"
    assert oil.category == "Масла и косметика"

    # Проверка условий поставщика
    conditions = (
        db_session.query(SupplierCondition).filter(SupplierCondition.item_id == oil.id).all()
    )
    assert len(conditions) == 2
    primary = next((c for c in conditions if c.is_primary), None)
    assert primary is not None
    assert primary.supplier.supplier_id == "SUP-AROMA"
    assert primary.estimated_price == Decimal("1250.00")


def test_load_seeds_idempotent_preserves_user_data(db_session: Session) -> None:
    """Повторный запуск: неизменность сидов и сохранение пользовательских данных."""
    # 1. Первый запуск загрузки сидов
    load_seeds(db_session)

    # 2. Пользователь добавляет свои записи
    custom_loc = Location(code="MS-03", name="Пользовательский SPA-филиал")
    custom_sup = Supplier(supplier_id="SUP-CUSTOM", name="Пользовательский поставщик")
    custom_item = Item(
        sku="CUSTOM-001",
        name="Пользовательский крем",
        category="Косметика",
        unit="шт",
    )
    db_session.add_all([custom_loc, custom_sup, custom_item])
    db_session.flush()

    # Пользовательское условие
    custom_cond = SupplierCondition(
        item_id=custom_item.id,
        supplier_id=custom_sup.id,
        lead_time_days=3,
        package_size=Decimal("1.000"),
        min_order_qty=Decimal("2.000"),
        estimated_price=Decimal("500.00"),
        is_primary=True,
    )
    db_session.add(custom_cond)

    # Пользователь изменяет название существующего сидового товара
    oil = db_session.query(Item).filter(Item.sku == "OIL-001").first()
    assert oil is not None
    oil.name = "Масло массажное миндальное (изменено пользователем)"

    db_session.commit()

    # 3. Второй запуск загрузки сидов
    second_stats = load_seeds(db_session)

    # Ни одна новая сидовая запись не должна быть добавлена повторно
    assert second_stats["locations"] == 0
    assert second_stats["suppliers"] == 0
    assert second_stats["items"] == 0
    assert second_stats["supplier_conditions"] == 0

    # Проверка итогового состава данных
    assert db_session.query(func.count(Location.id)).scalar() == len(SEED_LOCATIONS) + 1
    assert db_session.query(func.count(Supplier.id)).scalar() == len(SEED_SUPPLIERS) + 1
    assert db_session.query(func.count(Item.id)).scalar() == len(SEED_ITEMS) + 1
    assert db_session.query(func.count(SupplierCondition.id)).scalar() == len(SEED_CONDITIONS) + 1

    # Пользовательские данные сохранены в точности
    saved_custom_item = db_session.query(Item).filter(Item.sku == "CUSTOM-001").first()
    assert saved_custom_item is not None
    assert saved_custom_item.name == "Пользовательский крем"

    # Изменение пользователя в сидовой записи НЕ перезаписано
    refreshed_oil = db_session.query(Item).filter(Item.sku == "OIL-001").first()
    assert refreshed_oil is not None
    assert refreshed_oil.name == "Масло массажное миндальное (изменено пользователем)"

    # Партии и движения по-прежнему отсутствуют
    assert db_session.query(func.count(Batch.id)).scalar() == 0
    assert db_session.query(func.count(Movement.id)).scalar() == 0


def test_seed_cli_main(db_session: Session) -> None:
    """Проверка успешного выполнения точки входа main() CLI-загрузчика."""
    exit_code = main()
    assert exit_code == 0
    # Проверяем, что в базе есть записи
    assert db_session.query(func.count(Item.id)).scalar() >= len(SEED_ITEMS)
