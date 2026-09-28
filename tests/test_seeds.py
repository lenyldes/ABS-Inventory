"""Тесты начальных данных (сидов) и их идемпотентной загрузки."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.inventory.calculator import calculate_stock_balance
from app.inventory.common_validation import load_history
from app.inventory.operations import register_receipt
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Batch, Movement, MovementAllocation
from app.models.procurement import PurchaseOrder, SupplierCondition
from app.seeds.data import (
    SEED_CONDITIONS,
    SEED_ITEMS,
    SEED_LOCATIONS,
    SEED_MOVEMENTS,
    SEED_SUPPLIERS,
)
from app.seeds.loader import load_seeds, main


def test_seed_data_definitions_validity() -> None:
    """Проверка структуры и целостности исходных определений сидов."""
    assert len(SEED_LOCATIONS) >= 2
    assert len(SEED_SUPPLIERS) >= 2
    assert len(SEED_ITEMS) >= 3
    assert len(SEED_CONDITIONS) >= 4
    assert len(SEED_MOVEMENTS) >= 2

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

    # Движения ссылаются только на существующие SKU и объекты
    for m in SEED_MOVEMENTS:
        assert m["sku"] in skus
        assert m["location"] in codes
        assert m["quantity"] > 0


def test_load_seeds_first_run(db_session: Session) -> None:
    """Первый запуск: создание справочников, партий и стартовых движений."""
    stats = load_seeds(db_session)

    assert stats["locations"] == len(SEED_LOCATIONS)
    assert stats["suppliers"] == len(SEED_SUPPLIERS)
    assert stats["items"] == len(SEED_ITEMS)
    assert stats["supplier_conditions"] == len(SEED_CONDITIONS)
    assert stats["movements"] == len(SEED_MOVEMENTS)

    # Проверка записей в базе данных
    assert db_session.query(func.count(Location.id)).scalar() == len(SEED_LOCATIONS)
    assert db_session.query(func.count(Supplier.id)).scalar() == len(SEED_SUPPLIERS)
    assert db_session.query(func.count(Item.id)).scalar() == len(SEED_ITEMS)
    assert db_session.query(func.count(SupplierCondition.id)).scalar() == len(SEED_CONDITIONS)

    # Требование этапа 06: партии и движения созданы через складской сервис
    assert db_session.query(func.count(Movement.id)).scalar() == len(SEED_MOVEMENTS)
    assert db_session.query(func.count(Batch.id)).scalar() >= 2
    assert db_session.query(func.count(MovementAllocation.id)).scalar() >= 1
    assert db_session.query(func.count(PurchaseOrder.id)).scalar() == 0

    # Проверка вычисленного остатка по стартовым движениям
    oil = db_session.query(Item).filter(Item.sku == "OIL-001").first()
    loc_ms01 = db_session.query(Location).filter(Location.code == "MS-01").first()
    assert oil is not None
    assert loc_ms01 is not None

    _, _, b_snaps, m_snaps = load_history(db_session, oil.id, loc_ms01.id)
    balance = calculate_stock_balance(b_snaps, m_snaps, as_of=date.today())
    assert balance.current_stock == Decimal("16.000")  # 20.000 receipt - 4.000 consume
    assert balance.available_stock == Decimal("16.000")


def test_load_seeds_idempotent_preserves_user_data(db_session: Session) -> None:
    """Повторный запуск: неизменность сидов, отсутствие дублей
    и сохранение пользовательских записей.
    """
    # 1. Первый запуск загрузки сидов
    load_seeds(db_session)

    # 2. Пользователь добавляет свои записи в справочники и складское движение
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

    oil = db_session.query(Item).filter(Item.sku == "OIL-001").first()
    loc_ms01 = db_session.query(Location).filter(Location.code == "MS-01").first()
    assert oil is not None
    assert loc_ms01 is not None

    oil.name = "Масло массажное миндальное (изменено пользователем)"

    # Пользовательское движение поступления
    register_receipt(
        db_session,
        item=oil,
        location=loc_ms01,
        operation_date=date.today(),
        quantity=Decimal("5.000"),
        doc_number="USER-DOC-REC-999",
        batch_number="USER-BATCH-999",
        expiry_date=date(2027, 6, 1),
        unit_price=Decimal("1300.00"),
    )
    db_session.commit()

    # 3. Второй запуск загрузки сидов
    second_stats = load_seeds(db_session)

    # Ни одна новая сидовая запись не должна быть добавлена повторно
    assert second_stats["locations"] == 0
    assert second_stats["suppliers"] == 0
    assert second_stats["items"] == 0
    assert second_stats["supplier_conditions"] == 0
    assert second_stats["movements"] == 0

    # Проверка итогового состава данных
    assert db_session.query(func.count(Location.id)).scalar() == len(SEED_LOCATIONS) + 1
    assert db_session.query(func.count(Supplier.id)).scalar() == len(SEED_SUPPLIERS) + 1
    assert db_session.query(func.count(Item.id)).scalar() == len(SEED_ITEMS) + 1
    assert db_session.query(func.count(SupplierCondition.id)).scalar() == len(SEED_CONDITIONS) + 1
    assert db_session.query(func.count(Movement.id)).scalar() == len(SEED_MOVEMENTS) + 1

    # Изменение пользователя в сидовой записи НЕ перезаписано
    refreshed_oil = db_session.query(Item).filter(Item.sku == "OIL-001").first()
    assert refreshed_oil is not None
    assert refreshed_oil.name == "Масло массажное миндальное (изменено пользователем)"

    # Пользовательское движение сохранено и рассчитанный остаток увеличился на 5.000
    _, _, b_snaps, m_snaps = load_history(db_session, oil.id, loc_ms01.id)
    balance = calculate_stock_balance(b_snaps, m_snaps, as_of=date.today())
    assert balance.current_stock == Decimal("21.000")  # 16.000 + 5.000


def test_seed_cli_main(db_session: Session) -> None:
    """Проверка успешного выполнения точки входа main() CLI-загрузчика."""
    exit_code = main()
    assert exit_code == 0
    assert db_session.query(func.count(Item.id)).scalar() >= len(SEED_ITEMS)
    assert db_session.query(func.count(Movement.id)).scalar() >= len(SEED_MOVEMENTS)
