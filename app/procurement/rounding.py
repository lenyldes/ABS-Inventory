"""Чистые операции округления объёма заказа, цены и расчёта стоимости."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

QTY_QUANT = Decimal("0.001")
PRICE_QUANT = Decimal("0.01")
ZERO_QTY = Decimal("0.000")
ZERO_PRICE = Decimal("0.00")


def round_order_quantity(
    need: Decimal,
    package_size: Decimal | None = None,
    min_order_qty: Decimal | None = None,
) -> Decimal:
    """Округляет потребность с учётом минимального заказа, кратности упаковки и точности.

    Если потребность нулевая или отрицательная, возвращается 0.000 (условия
    минимального заказа и упаковки не применяются при отсутствии потребности).
    При положительной потребности сначала применяется минимальный заказ,
    затем кратность упаковки (округление вверх до целого числа упаковок),
    либо округление до 0.001 с ROUND_HALF_UP.
    """
    if need <= ZERO_QTY:
        return ZERO_QTY

    effective = need
    if min_order_qty is not None and min_order_qty > ZERO_QTY:
        effective = max(effective, min_order_qty)

    if package_size is not None and package_size > ZERO_QTY:
        num_packages = (effective / package_size).to_integral_value(rounding=ROUND_CEILING)
        return (num_packages * package_size).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)

    return effective.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


def round_unit_price(unit_price: Decimal | None) -> Decimal | None:
    """Округляет цену за единицу до 0.01 рубля с ROUND_HALF_UP.

    Если цена не задана (None), возвращает None.
    """
    if unit_price is None:
        return None
    return unit_price.quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


def calculate_total_cost(
    quantity: Decimal,
    unit_price: Decimal | None,
) -> Decimal | None:
    """Рассчитывает общую стоимость позиции в рублях до копеек (ROUND_HALF_UP).

    Если цена не задана (None), возвращает None.
    В расчёте используется округлённая цена unit_price.
    """
    rounded_price = round_unit_price(unit_price)
    if rounded_price is None:
        return None
    return (quantity * rounded_price).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
