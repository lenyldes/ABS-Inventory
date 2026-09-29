"""Тесты изолированной пересборки демонстрационных данных (--replace)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.demo_data.__main__ import main
from app.demo_data.catalog import (
    DEMO_ITEM_SKUS,
)
from app.demo_data.inspection import DemoDataError, detect_demo_as_of
from app.demo_data.loader import prepare_demo_data
from app.demo_data.movements import (
    DEMO_BASE_RECEIPT_DOC,
    DEMO_MOVEMENT_DOC_NUMBERS,
)
from app.inventory.operations import register_receipt
from app.models.amendments import AmendmentEntry, AmendmentSet
from app.models.catalog import Item, Location, Supplier
from app.models.inventory import Movement
from app.models.procurement import PurchaseOrder, SupplierCondition


def test_replace_demo_data_different_as_of(db_session: Session) -> None:
    """Замена демонстрационного набора на иную дату актуальности."""
    initial_as_of = date(2026, 9, 1)
    new_as_of = date(2026, 9, 29)

    mode1, _ = prepare_demo_data(db_session, as_of=initial_as_of)
    assert mode1 == "created"
    assert detect_demo_as_of(db_session) == initial_as_of

    base_m1 = (
        db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).first()
    )
    assert base_m1 is not None
    assert base_m1.operation_date == initial_as_of - timedelta(days=100)

    mode2, stats2 = prepare_demo_data(db_session, as_of=new_as_of, replace=True)
    assert mode2 == "replaced"
    assert stats2["items"] == len(DEMO_ITEM_SKUS)
    assert stats2["movements"] == len(DEMO_MOVEMENT_DOC_NUMBERS)
    assert detect_demo_as_of(db_session) == new_as_of

    base_m2 = (
        db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).first()
    )
    assert base_m2 is not None
    assert base_m2.operation_date == new_as_of - timedelta(days=100)


def test_replace_demo_data_same_as_of(db_session: Session) -> None:
    """Замена демонстрационного набора на ту же дату при явном флаге --replace."""
    target_as_of = date(2026, 9, 29)
    mode1, _ = prepare_demo_data(db_session, as_of=target_as_of)
    assert mode1 == "created"

    mode2, stats2 = prepare_demo_data(db_session, as_of=target_as_of, replace=True)
    assert mode2 == "replaced"
    assert stats2["items"] == len(DEMO_ITEM_SKUS)
    assert detect_demo_as_of(db_session) == target_as_of


def test_replace_preserves_unrelated_custom_records(db_session: Session) -> None:
    """Сохранность независимых пользовательских записей при пересборке."""
    prepare_demo_data(db_session, as_of=date(2026, 9, 1))

    # Пользовательские справочники и движение
    custom_loc = Location(code="CUSTOM-MS-99", name="Пользовательский SPA")
    custom_sup = Supplier(supplier_id="CUSTOM-SUP-99", name="Пользовательский поставщик")
    custom_item = Item(
        sku="CUSTOM-ITEM-99",
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
        min_order_qty=Decimal("1.000"),
        estimated_price=Decimal("200.00"),
        is_primary=True,
    )
    db_session.add(custom_cond)

    register_receipt(
        db_session,
        item=custom_item,
        location=custom_loc,
        operation_date=date(2026, 9, 1),
        quantity=Decimal("15.000"),
        doc_number="CUSTOM-REC-999",
        batch_number="CUSTOM-BATCH-999",
        expiry_date=date(2027, 1, 1),
        unit_price=Decimal("180.00"),
        supplier_id="CUSTOM-SUP-99",
    )
    db_session.commit()

    # Пересборка демонабора на новую дату
    mode, _ = prepare_demo_data(db_session, as_of=date(2026, 9, 29), replace=True)
    assert mode == "replaced"

    # Проверка, что пользовательские записи сохранены без изменений
    refreshed_loc = db_session.query(Location).filter(Location.code == "CUSTOM-MS-99").first()
    refreshed_sup = (
        db_session.query(Supplier).filter(Supplier.supplier_id == "CUSTOM-SUP-99").first()
    )
    refreshed_item = db_session.query(Item).filter(Item.sku == "CUSTOM-ITEM-99").first()
    refreshed_m = db_session.query(Movement).filter(Movement.doc_number == "CUSTOM-REC-999").first()

    assert refreshed_loc is not None
    assert refreshed_sup is not None
    assert refreshed_item is not None
    assert refreshed_m is not None
    assert refreshed_m.quantity == Decimal("15.000")


def test_replace_refuses_when_foreign_movement_references_demo(db_session: Session) -> None:
    """Отказ в пересборке при наличии стороннего движения, ссылающегося на демотовар."""
    as_of = date(2026, 9, 29)
    prepare_demo_data(db_session, as_of=as_of)

    demo_oil = db_session.query(Item).filter(Item.sku == "DEMO-OIL").first()
    demo_loc = db_session.query(Location).filter(Location.code == "DEMO-MS-01").first()
    assert demo_oil is not None and demo_loc is not None

    # Стороннее движение на демотовар
    foreign_m = Movement(
        operation_date=as_of,
        item_id=demo_oil.id,
        location_id=demo_loc.id,
        type="consume",
        quantity=Decimal("2.000"),
        doc_number="FOREIGN-CONS-001",
        status="active",
        current_version=1,
    )
    db_session.add(foreign_m)
    db_session.commit()

    with pytest.raises(DemoDataError, match="стороннее складское движение"):
        prepare_demo_data(db_session, as_of=date(2026, 9, 20), replace=True)

    # Демонабор не удален, стороннее движение сохранено
    assert db_session.query(Item).filter(Item.sku == "DEMO-OIL").first() is not None
    foreign_saved = (
        db_session.query(Movement).filter(Movement.doc_number == "FOREIGN-CONS-001").first()
    )
    assert foreign_saved is not None


def test_replace_refuses_when_foreign_order_references_demo(db_session: Session) -> None:
    """Отказ в пересборке при наличии стороннего заказа, ссылающегося на демотовар."""
    as_of = date(2026, 9, 29)
    prepare_demo_data(db_session, as_of=as_of)

    demo_oil = db_session.query(Item).filter(Item.sku == "DEMO-OIL").first()
    demo_loc = db_session.query(Location).filter(Location.code == "DEMO-MS-01").first()
    demo_sup = db_session.query(Supplier).filter(Supplier.supplier_id == "DEMO-SUP-MAIN").first()
    assert demo_oil is not None and demo_loc is not None and demo_sup is not None

    foreign_po = PurchaseOrder(
        item_id=demo_oil.id,
        location_id=demo_loc.id,
        supplier_id=demo_sup.id,
        doc_number="FOREIGN-PO-001",
        expected_date=as_of + timedelta(days=5),
        expected_qty=Decimal("10.000"),
        received_qty=Decimal("0.000"),
        pending_qty=Decimal("10.000"),
        unit_price=Decimal("100.00"),
        status="pending",
    )
    db_session.add(foreign_po)
    db_session.commit()

    with pytest.raises(DemoDataError, match="сторонний заказ поставщику"):
        prepare_demo_data(db_session, as_of=date(2026, 9, 20), replace=True)

    # Заказ сохранен, демонабор не затронут
    foreign_po_saved = (
        db_session.query(PurchaseOrder).filter(PurchaseOrder.doc_number == "FOREIGN-PO-001").first()
    )
    assert foreign_po_saved is not None


def test_replace_refuses_when_foreign_amendment_references_demo(db_session: Session) -> None:
    """Отказ в пересборке при наличии строки исправления (AmendmentEntry) на демодвижение."""
    as_of = date(2026, 9, 29)
    prepare_demo_data(db_session, as_of=as_of)

    base_m = db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).first()
    assert base_m is not None

    am_set = AmendmentSet(
        amendment_id="AMEND-DEMO-01",
        reason="Тестовое исправление",
        status="preview",
        version_signature="sig-test-1",
    )
    db_session.add(am_set)
    db_session.flush()

    am_entry = AmendmentEntry(
        amendment_set_id=am_set.id,
        movement_id=base_m.id,
        action="update",
        expected_version=1,
        details={"quantity": "150.000"},
    )
    db_session.add(am_entry)
    db_session.commit()

    with pytest.raises(DemoDataError, match="строка исправления"):
        prepare_demo_data(db_session, as_of=date(2026, 9, 20), replace=True)


def test_replace_rollback_on_failure(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Откат всех изменений при ошибке во время пересборки."""
    initial_as_of = date(2026, 9, 1)
    prepare_demo_data(db_session, as_of=initial_as_of)

    base_m = db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).first()
    assert base_m is not None
    original_id = base_m.id

    def mock_fail(*args, **kwargs):
        raise RuntimeError("Искусственный сбой при загрузке нового набора")

    monkeypatch.setattr("app.demo_data.loader.load_demo_data", mock_fail)

    with pytest.raises(RuntimeError, match="Искусственный сбой"):
        prepare_demo_data(db_session, as_of=date(2026, 9, 29), replace=True)

    # Транзакция откатилась: старые записи на месте, исходная дата сохранилась
    refreshed_m = (
        db_session.query(Movement).filter(Movement.doc_number == DEMO_BASE_RECEIPT_DOC).first()
    )
    assert refreshed_m is not None
    assert refreshed_m.id == original_id
    assert detect_demo_as_of(db_session) == initial_as_of


def test_cli_replace_option(db_session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    """Проверка работы CLI с флагом --replace."""
    prepare_demo_data(db_session, as_of=date(2026, 9, 1))

    exit_code = main(["--as-of", "2026-09-29", "--replace"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Режим: пересобран" in captured.out
    assert "2026-09-29" in captured.out
    assert detect_demo_as_of(db_session) == date(2026, 9, 29)
