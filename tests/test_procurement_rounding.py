"""Тесты общих чистых операций округления объёма, цены и стоимости."""

from decimal import Decimal

import pytest

from app.procurement.rounding import (
    calculate_total_cost,
    round_order_quantity,
    round_unit_price,
)


class TestRoundOrderQuantity:
    """Проверка чистой функции округления объёма заказа round_order_quantity."""

    def test_zero_need_returns_zero(self) -> None:
        """Нулевая потребность возвращает 0.000 независимо от условий."""
        assert round_order_quantity(Decimal("0.000")) == Decimal("0.000")
        assert round_order_quantity(
            Decimal("0.000"),
            package_size=Decimal("10.000"),
            min_order_qty=Decimal("50.000"),
        ) == Decimal("0.000")

    def test_negative_need_returns_zero(self) -> None:
        """Отрицательная потребность (избыток) возвращает 0.000."""
        assert round_order_quantity(Decimal("-5.123")) == Decimal("0.000")
        assert round_order_quantity(
            Decimal("-10.000"),
            package_size=Decimal("5.000"),
            min_order_qty=Decimal("20.000"),
        ) == Decimal("0.000")

    def test_min_order_qty_applied_when_need_is_less(self) -> None:
        """При потребности меньше минимума объём поднимается до min_order_qty."""
        res = round_order_quantity(Decimal("4.500"), min_order_qty=Decimal("10.000"))
        assert res == Decimal("10.000")

    def test_min_order_qty_not_increasing_larger_need(self) -> None:
        """При потребности больше минимума объём не занижается."""
        res = round_order_quantity(Decimal("15.200"), min_order_qty=Decimal("10.000"))
        assert res == Decimal("15.200")

    def test_package_size_exact_multiple(self) -> None:
        """Если потребность кратна упаковке, дополнительного увеличения не происходит."""
        res = round_order_quantity(Decimal("15.000"), package_size=Decimal("5.000"))
        assert res == Decimal("15.000")

    def test_package_size_rounds_up_to_next_package(self) -> None:
        """Если потребность не кратна упаковке, округление идёт строго вверх."""
        res = round_order_quantity(Decimal("15.001"), package_size=Decimal("5.000"))
        assert res == Decimal("20.000")

    def test_package_size_and_min_order_combination(self) -> None:
        """Комбинация min_order и упаковки: сначала минимум, затем кратность вверх."""
        # Потребность 7, минимум 10, упаковка 3 -> ceil(10 / 3) = 4 упаковки = 12
        res = round_order_quantity(
            Decimal("7.000"),
            package_size=Decimal("3.000"),
            min_order_qty=Decimal("10.000"),
        )
        assert res == Decimal("12.000")

    def test_package_size_fractional(self) -> None:
        """Проверка работы с дробным размером упаковки (например, 0.25 кг)."""
        # Потребность 0.6, упаковка 0.25 -> 3 упаковки = 0.75
        res = round_order_quantity(Decimal("0.600"), package_size=Decimal("0.250"))
        assert res == Decimal("0.750")

    def test_no_constraints_preserves_three_decimal_precision(self) -> None:
        """Без ограничений объём округляется до 3 знаков (ROUND_HALF_UP)."""
        assert round_order_quantity(Decimal("3.1234")) == Decimal("3.123")
        assert round_order_quantity(Decimal("3.1235")) == Decimal("3.124")


class TestRoundUnitPrice:
    """Проверка функции округления цены round_unit_price."""

    def test_none_unit_price_returns_none(self) -> None:
        """Отсутствующая цена возвращает None."""
        assert round_unit_price(None) is None

    def test_exact_price_unchanged(self) -> None:
        """Цена с двумя знаками сохраняется без изменений."""
        assert round_unit_price(Decimal("150.50")) == Decimal("150.50")

    @pytest.mark.parametrize(
        ("raw_price", "expected"),
        [
            (Decimal("10.554"), Decimal("10.55")),
            (Decimal("10.555"), Decimal("10.56")),
            (Decimal("10.556"), Decimal("10.56")),
            (Decimal("0.001"), Decimal("0.00")),
            (Decimal("0.005"), Decimal("0.01")),
        ],
    )
    def test_price_round_half_up(self, raw_price: Decimal, expected: Decimal) -> None:
        """Округление цены до сотых по правилу ROUND_HALF_UP."""
        assert round_unit_price(raw_price) == expected


class TestCalculateTotalCost:
    """Проверка расчёта стоимости calculate_total_cost."""

    def test_none_price_yields_none_cost(self) -> None:
        """При отсутствии цены стоимость не может быть рассчитана (None)."""
        assert calculate_total_cost(Decimal("10.000"), None) is None
        assert calculate_total_cost(Decimal("0.000"), None) is None

    def test_zero_quantity_with_price_yields_zero_cost(self) -> None:
        """При нулевом объёме и известной цене стоимость равна 0.00."""
        assert calculate_total_cost(Decimal("0.000"), Decimal("123.45")) == Decimal("0.00")

    def test_quantity_multiplication_with_price_rounding(self) -> None:
        """Цена предварительно округляется до сотых перед умножением."""
        # Цена 10.555 -> 10.56, стоимость: 7 * 10.56 = 73.92
        cost = calculate_total_cost(Decimal("7.000"), Decimal("10.555"))
        assert cost == Decimal("73.92")

    def test_fractional_kopecks_rounded_half_up(self) -> None:
        """Итоговая стоимость округляется до 0.01 рубля с ROUND_HALF_UP."""
        # 1.500 * 1.05 = 1.575 -> 1.58
        cost = calculate_total_cost(Decimal("1.500"), Decimal("1.05"))
        assert cost == Decimal("1.58")

        # 3.333 * 10.00 = 33.330 -> 33.33
        cost_down = calculate_total_cost(Decimal("3.333"), Decimal("10.00"))
        assert cost_down == Decimal("33.33")
