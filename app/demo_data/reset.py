"""Возвращает данные постоянного демостенда к исходному состоянию при запуске."""

import sys

from sqlalchemy import text

from app.core.database import REQUIRED_TABLES, get_engine


def reset_demo_database() -> None:
    """Очищает предметные таблицы после миграций в одной транзакции.

    Ревизия Alembic сохраняется, чтобы новый запуск мог применить будущие миграции.
    Сиды и контрольный набор загружаются отдельными шагами запуска.
    """
    engine = get_engine()
    names = ", ".join(
        engine.dialect.identifier_preparer.quote(name) for name in sorted(REQUIRED_TABLES)
    )
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


def main() -> int:
    """Возвращает код ошибки без вывода адреса и пароля базы данных."""
    try:
        reset_demo_database()
    except Exception:
        print("Ошибка сброса данных демостенда", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
