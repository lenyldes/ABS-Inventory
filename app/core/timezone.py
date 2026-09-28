"""Работа с часовыми поясами сервиса (Europe/Moscow)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def today_in_moscow() -> date:
    """Возвращает текущую календарную дату в часовом поясе Europe/Moscow."""
    return datetime.now(MOSCOW_TZ).date()
