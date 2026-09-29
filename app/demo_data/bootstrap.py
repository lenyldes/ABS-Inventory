"""Однократная подготовка демонабора при запуске приложения."""

import sys
from datetime import date

from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.core.timezone import today_in_moscow
from app.demo_data.inspection import (
    DemoDataError,
    get_existing_demo_keys,
    require_demo_as_of,
)
from app.demo_data.loader import prepare_demo_data


def bootstrap_demo_data(session: Session) -> date:
    """Создаёт отсутствующий набор или проверяет существующий без записи."""
    keys = get_existing_demo_keys(session)
    if not any(keys.values()):
        as_of = today_in_moscow()
        prepare_demo_data(session, as_of)
        return as_of
    return require_demo_as_of(session)


def main() -> int:
    """Проверяет демонабор до запуска HTTP-сервиса."""
    try:
        with get_session_factory()() as session:
            bootstrap_demo_data(session)
    except DemoDataError as error:
        print(f"Ошибка подготовки демонабора: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("Ошибка подготовки демонабора: проверьте базу данных", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
