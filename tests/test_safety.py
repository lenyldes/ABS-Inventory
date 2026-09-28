"""Тесты защитного отказа при попытке выполнения тестов на небезопасной БД."""

import pytest

from tests.safety import (
    DatabaseSafetyViolationError,
    ensure_truncate_safety,
    validate_test_database_safety,
)


def test_safety_rejects_non_test_app_env() -> None:
    """Проверка защитного отказа, если APP_ENV не равен 'test'."""
    with pytest.raises(DatabaseSafetyViolationError, match="APP_ENV должна иметь значение 'test'"):
        validate_test_database_safety(
            app_env="development",
            test_db_url="postgresql+psycopg://user:pass@localhost:5432/abs_inventory_test",
        )

    with pytest.raises(DatabaseSafetyViolationError, match="APP_ENV должна иметь значение 'test'"):
        validate_test_database_safety(
            app_env=None,
            test_db_url="postgresql+psycopg://user:pass@localhost:5432/abs_inventory_test",
        )


def test_safety_rejects_missing_test_database_url() -> None:
    """Проверка защитного отказа, если TEST_DATABASE_URL не задан."""
    with pytest.raises(DatabaseSafetyViolationError, match="TEST_DATABASE_URL не задана"):
        validate_test_database_safety(app_env="test", test_db_url=None)

    with pytest.raises(DatabaseSafetyViolationError, match="TEST_DATABASE_URL не задана"):
        validate_test_database_safety(app_env="test", test_db_url="")


def test_safety_rejects_reserved_database_names() -> None:
    """Проверка защитного отказа при указании рабочей или системной БД."""
    for reserved in ("abs_inventory", "postgres"):
        with pytest.raises(DatabaseSafetyViolationError, match="зарезервирована для рабочей"):
            validate_test_database_safety(
                app_env="test",
                test_db_url=f"postgresql+psycopg://user:pass@localhost:5432/{reserved}",
            )


def test_safety_rejects_matching_main_and_test_urls() -> None:
    """Проверка защитного отказа, если TEST_DATABASE_URL совпадает с рабочей БД."""
    url = "postgresql+psycopg://user:pass@db:5432/abs_inventory_custom"
    with pytest.raises(DatabaseSafetyViolationError, match="указывает на ту же базу данных"):
        validate_test_database_safety(
            app_env="test",
            test_db_url=url,
            main_db_url=url,
        )


def test_safety_accepts_valid_test_configuration() -> None:
    """Проверка успешного прохождения валидации при изолированной конфигурации."""
    validate_test_database_safety(
        app_env="test",
        test_db_url="postgresql+psycopg://user:pass@db:5432/abs_inventory_test",
        main_db_url="postgresql+psycopg://user:pass@db:5432/abs_inventory",
    )


def test_truncate_safety_blocks_production_and_invalid_dbs() -> None:
    """Проверка защитной блокировки TRUNCATE на небезопасных БД."""
    with pytest.raises(DatabaseSafetyViolationError, match="APP_ENV='development'"):
        ensure_truncate_safety(
            current_database="abs_inventory_test",
            app_env="development",
        )

    for db_name in ("abs_inventory", "postgres", "", None):
        with pytest.raises(DatabaseSafetyViolationError, match="не является тестовой"):
            ensure_truncate_safety(
                current_database=db_name,
                app_env="test",
            )


def test_truncate_safety_allows_valid_test_db() -> None:
    """Проверка разрешения TRUNCATE только для изолированной тестовой базы."""
    ensure_truncate_safety(
        current_database="abs_inventory_test",
        app_env="test",
    )
