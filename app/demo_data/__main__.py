"""CLI-команда подготовки и проверки демонстрационных данных."""

import argparse
import sys
from datetime import date, datetime

from app.core.database import check_database_readiness, get_session_factory
from app.core.timezone import today_in_moscow
from app.demo_data.loader import DemoDataError, prepare_demo_data


def parse_as_of(date_str: str) -> date:
    """Парсит и проверяет контрольную дату as_of по Москве.

    Дата должна соответствовать формату YYYY-MM-DD и не должна быть
    в будущем относительно текущей календарной даты в Europe/Moscow.
    """
    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError) as err:
        raise ValueError(f"Неверный формат даты '{date_str}', ожидается YYYY-MM-DD") from err

    moscow_today = today_in_moscow()
    if parsed_date > moscow_today:
        raise ValueError(
            f"Дата as_of ({parsed_date.isoformat()}) не может быть в будущем "
            f"относительно текущей даты по Москве ({moscow_today.isoformat()})"
        )
    return parsed_date


def format_summary(as_of: date, mode: str, stats: dict[str, int]) -> str:
    """Форматирует краткую сводку результата подготовки набора."""
    mode_names = {
        "created": "создан",
        "idempotent": "повтор (без изменений)",
        "replaced": "пересобран",
    }
    mode_str = mode_names.get(mode, mode)
    return (
        f"Демонстрационные данные успешно подготовлены.\n"
        f"Контрольная дата (as_of): {as_of.isoformat()}\n"
        f"Режим: {mode_str}\n"
        f"Объектов: {stats['locations']}\n"
        f"Поставщиков: {stats['suppliers']}\n"
        f"Товаров: {stats['items']}\n"
        f"Закупочных условий: {stats['supplier_conditions']}\n"
        f"Складских движений: {stats['movements']}\n"
        f"Партий: {stats['batches']}\n"
        f"Ожидаемых заказов: {stats['orders']}"
    )


def create_parser() -> argparse.ArgumentParser:
    """Создает парсер аргументов командной строки."""
    parser = argparse.ArgumentParser(
        prog="python -m app.demo_data",
        description="Подготовка и проверка демонстрационного набора данных.",
    )
    parser.add_argument(
        "--as-of",
        required=True,
        dest="as_of",
        help="Контрольная дата набора в формате YYYY-MM-DD (не позже сегодняшней по Москве)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        default=False,
        help="Разрешить изолированную замену существующего демонстрационного набора",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Основная точка входа CLI."""
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as err:
        return err.code if isinstance(err.code, int) else 2

    try:
        as_of = parse_as_of(args.as_of)
    except ValueError as err:
        sys.stderr.write(f"Ошибка параметров: {err}\n")
        return 1

    is_ready, status_detail = check_database_readiness()
    if not is_ready:
        sys.stderr.write(
            f"База данных недоступна или не готова к загрузке данных (статус: {status_detail})\n"
        )
        return 1

    session_factory = get_session_factory()
    try:
        with session_factory() as session:
            mode, stats = prepare_demo_data(session, as_of=as_of, replace=args.replace)
        print(format_summary(as_of, mode, stats))
        return 0
    except DemoDataError as err:
        sys.stderr.write(f"Ошибка демонстрационных данных: {err}\n")
        return 1
    except NotImplementedError as err:
        sys.stderr.write(f"Операция не поддерживается: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(
            f"Непредвиденная ошибка при подготовке данных: {type(err).__name__}: {err}\n"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
