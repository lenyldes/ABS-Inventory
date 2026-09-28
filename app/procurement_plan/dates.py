"""Календарные операции и расчёт интервалов покрытия для плана закупок."""

import calendar
from datetime import date


def add_one_month(d: date) -> date:
    """Прибавляет один календарный месяц со сдвигом на последний день месяца.

    Например:
    31.01 + 1 месяц = 28.02 (или 29.02 в високосный год).
    31.08 + 1 месяц = 30.09.
    15.09 + 1 месяц = 15.10.
    """
    total_months = d.month + 1 - 1
    target_year = d.year + (total_months // 12)
    target_month = (total_months % 12) + 1
    max_day = calendar.monthrange(target_year, target_month)[1]
    target_day = min(d.day, max_day)
    return date(target_year, target_month, target_day)


def compute_coverage_interval(delivery_date: date, horizon_end: date) -> tuple[date, date]:
    """Вычисляет границы интервала покрытия заказа [coverage_start, coverage_end].

    Покрываемый интервал начинается в дату прихода поставки и длится примерно
    один календарный месяц, но не далее окончания горизонта планирования.
    """
    coverage_start = delivery_date
    coverage_end = min(add_one_month(delivery_date), horizon_end)
    return coverage_start, coverage_end


def generate_horizon_months(as_of: date, horizon_end: date) -> list[tuple[str, int, int, bool]]:
    """Генерирует список календарных месяцев горизонта с признаком неполного месяца.

    Возвращает список кортежей:
    (month_key "YYYY-MM", year, month_number, is_partial)
    """
    months: list[tuple[str, int, int, bool]] = []
    curr_year = as_of.year
    curr_month = as_of.month

    while (curr_year, curr_month) <= (horizon_end.year, horizon_end.month):
        month_str = f"{curr_year:04d}-{curr_month:02d}"
        last_day = calendar.monthrange(curr_year, curr_month)[1]

        is_first = curr_year == as_of.year and curr_month == as_of.month
        is_last = curr_year == horizon_end.year and curr_month == horizon_end.month

        if is_first and is_last:
            is_partial = as_of.day != 1 or horizon_end.day != last_day
        elif is_first:
            is_partial = as_of.day != 1
        elif is_last:
            is_partial = horizon_end.day != last_day
        else:
            is_partial = False

        months.append((month_str, curr_year, curr_month, is_partial))

        if curr_month == 12:
            curr_year += 1
            curr_month = 1
        else:
            curr_month += 1

    return months
