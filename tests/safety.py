"""Модуль защиты данных: предотвращает случайный запуск тестов на рабочей БД."""

from sqlalchemy.engine import make_url


class DatabaseSafetyViolationError(RuntimeError):
    """Исключение при попытке выполнения тестов на небезопасной или рабочей БД."""

    pass


def validate_test_database_safety(
    app_env: str | None,
    test_db_url: str | None,
    main_db_url: str | None = None,
) -> None:
    """Проверяет безопасность конфигурации для выполнения тестов.

    Требования:
    1. APP_ENV строго равен 'test'.
    2. TEST_DATABASE_URL явно задан.
    3. Имя базы данных не относится к рабочей или системной (abs_inventory, postgres).
    4. TEST_DATABASE_URL не указывает на ту же базу данных, что и main_db_url.
    """
    if app_env != "test":
        raise DatabaseSafetyViolationError(
            f"Запуск тестов запрещён: переменная APP_ENV должна иметь значение 'test', "
            f"текущее значение: {app_env!r}"
        )

    if not test_db_url:
        raise DatabaseSafetyViolationError(
            "Запуск тестов запрещён: переменная TEST_DATABASE_URL не задана."
        )

    test_url = make_url(test_db_url)
    if not test_url.database:
        raise DatabaseSafetyViolationError(
            "Запуск тестов запрещён: в TEST_DATABASE_URL не указано имя базы данных."
        )

    if test_url.database in ("abs_inventory", "postgres"):
        raise DatabaseSafetyViolationError(
            f"Запуск тестов запрещён: база данных '{test_url.database}' "
            f"зарезервирована для рабочей/системной среды."
        )

    if main_db_url:
        main_url = make_url(main_db_url)
        test_host = test_url.host or "localhost"
        main_host = main_url.host or "localhost"
        test_port = test_url.port or 5432
        main_port = main_url.port or 5432

        if (
            test_host == main_host
            and test_port == main_port
            and test_url.database == main_url.database
        ):
            raise DatabaseSafetyViolationError(
                f"Запуск тестов запрещён: TEST_DATABASE_URL указывает на ту же базу данных, "
                f"что и рабочая БД ('{test_url.database}')."
            )


def ensure_truncate_safety(
    current_database: str | None,
    app_env: str | None,
) -> None:
    """Защитный барьер перед TRUNCATE: запрещает очистку не-тестовых баз данных."""
    if app_env != "test":
        raise DatabaseSafetyViolationError(
            f"Очистка БД запрещена: APP_ENV={app_env!r} (требуется 'test')."
        )
    if not current_database or current_database in ("abs_inventory", "postgres"):
        raise DatabaseSafetyViolationError(
            f"Очистка БД запрещена: целевая база данных '{current_database}' не является тестовой!"
        )
