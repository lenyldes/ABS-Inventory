"""Интеграционные тесты изоляции транзакции снимка БД и сохранности данных."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import Item
from app.procurement_plan.repository import set_repeatable_read_snapshot


def test_set_repeatable_read_snapshot_preserves_uncommitted_data_on_conflict(
    db_session: Session,
) -> None:
    """Отказ установки REPEATABLE READ при активной транзакции не приводит к скрытому откату."""
    # 1. В сессию добавляется тестовый объект и выполняется flush,
    # чтобы перевести транзакцию в активное состояние.
    item = Item(
        sku="SKU-SNAPSHOT-UNCOMMITTED",
        name="Временный товар снимка",
        category="Тестовая категория",
        unit="шт",
    )
    db_session.add(item)
    db_session.flush()

    assert db_session.in_transaction()

    # 2. Ожидается RuntimeError при попытке сменить уровень изоляции в активной транзакции
    with pytest.raises(
        RuntimeError,
        match="Невозможно установить уровень изоляции REPEATABLE READ",
    ):
        set_repeatable_read_snapshot(db_session)

    # 3. Проверка: транзакция осталась активной, незакоммиченные данные сохранены в сессии
    assert db_session.in_transaction()
    persisted_item = db_session.execute(
        select(Item).where(Item.sku == "SKU-SNAPSHOT-UNCOMMITTED")
    ).scalar_one_or_none()
    assert persisted_item is not None
    assert persisted_item.name == "Временный товар снимка"

    # 4. Явный откат сессии для очистки после завершения проверки
    db_session.rollback()
    cleaned_item = db_session.execute(
        select(Item).where(Item.sku == "SKU-SNAPSHOT-UNCOMMITTED")
    ).scalar_one_or_none()
    assert cleaned_item is None
