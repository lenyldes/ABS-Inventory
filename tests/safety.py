"""Модуль защиты данных: предотвращает случайный запуск тестов на рабочей БД."""

from sqlalchemy.engine import make_url


class DatabaseSafetyViolationError(RuntimeError):
    """Исключение при попытке выполнения тестов на небезопасной или рабочей БД."""

    pass


def _is_same_database(url_str_1: str, url_str_2: str) -> bool:
    """Проверяет, указывают ли два URL на одну и ту же базу данных (хост, порт, имя БД)."""
    try:
        u1 = make_url(url_str_1)
        u2 = make_url(url_str_2)
    except Exception:
        return False
    h1 = u1.host or "localhost"
    h2 = u2.host or "localhost"
    p1 = u1.port or 5432
    p2 = u2.port or 5432
    return (h1 == h2) and (p1 == p2) and (u1.database == u2.database)


def validate_test_database_safety(
    app_env: str | None,
    test_db_url: str | None,
    main_db_url: str | None = None,
) -> None:
    """Проверяет безопасность конфигурации для выполнения тестов.

    Требования:
    1. APP_ENV строго равен 'test'.
    2. TEST_DATABASE_URL явно задан.
    3. Имя базы данных не относится к рабочей или системной (abs_inventory, postgres)
       и обязательно содержит подстроку 'test'.
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

    if "test" not in test_url.database.lower():
        raise DatabaseSafetyViolationError(
            f"Запуск тестов запрещён: имя тестовой базы данных '{test_url.database}' "
            f"должно содержать подстроку 'test' для защиты рабочей БД."
        )

    if main_db_url and _is_same_database(test_db_url, main_db_url):
        raise DatabaseSafetyViolationError(
            f"Запуск тестов запрещён: TEST_DATABASE_URL указывает на ту же базу данных, "
            f"что и рабочая БД ('{test_url.database}')."
        )


def ensure_truncate_safety(
    current_database: str | None,
    app_env: str | None,
    test_db_url: str | None = None,
    prohibited_db_urls: tuple[str | None, ...] = (),
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

    if "test" not in current_database.lower():
        raise DatabaseSafetyViolationError(
            f"Очистка БД запрещена: имя базы данных '{current_database}' "
            f"должно содержать подстроку 'test'!"
        )

    if test_db_url:
        expected_test_db = make_url(test_db_url).database
        if current_database != expected_test_db:
            raise DatabaseSafetyViolationError(
                f"Очистка БД запрещена: целевая база данных '{current_database}' "
                f"не совпадает с ожидаемой тестовой базой '{expected_test_db}'."
            )

    for prob_url in prohibited_db_urls:
        if prob_url:
            prob_db = make_url(prob_url).database
            if current_database == prob_db:
                raise DatabaseSafetyViolationError(
                    f"Очистка БД запрещена: целевая база данных '{current_database}' "
                    f"совпадает с запрещенной рабочей базой данных."
                )
