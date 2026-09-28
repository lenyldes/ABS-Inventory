"""Предметные аналитические разрезы плана закупок: по SKU, категориям и объектам."""

from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_UP

from app.api.plan_breakdown_schemas import (
    PlanCategoryBreakdownItem,
    PlanLocationBreakdownItem,
    PlanSkuBreakdownItem,
)
from app.api.plan_schemas import PlanItemSchema
from app.procurement.rounding import (
    PRICE_QUANT,
    QTY_QUANT,
    ZERO_PRICE,
    ZERO_QTY,
)


def build_sku_breakdown(
    items: Sequence[PlanItemSchema],
    sku_names: dict[str, str] | None = None,
    sku_categories: dict[str, str] | None = None,
) -> list[PlanSkuBreakdownItem]:
    """Строит предметный разрез бюджета по артикулам (SKU)."""
    groups: dict[str, list[PlanItemSchema]] = defaultdict(list)
    for it in items:
        groups[it.sku].append(it)

    result: list[PlanSkuBreakdownItem] = []
    for sku in sorted(groups.keys()):
        sku_items = groups[sku]
        items_count = len(sku_items)
        total_qty = sum((it.quantity for it in sku_items), ZERO_QTY).quantize(
            QTY_QUANT, rounding=ROUND_HALF_UP
        )
        known_total = sum(
            (it.total_cost for it in sku_items if it.total_cost is not None),
            ZERO_PRICE,
        ).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
        unpriced_count = sum(1 for it in sku_items if it.total_cost is None)
        is_price_complete = unpriced_count == 0
        has_unpriced = unpriced_count > 0

        name = (sku_names.get(sku) if sku_names else None) or sku_items[0].name
        category = (sku_categories.get(sku) if sku_categories else None) or sku_items[0].category

        result.append(
            PlanSkuBreakdownItem(
                sku=sku,
                name=name,
                category=category,
                known_total=known_total,
                total_cost=known_total,
                total_quantity=total_qty,
                items_count=items_count,
                unknown_price_count=unpriced_count,
                unpriced_items_count=unpriced_count,
                is_price_complete=is_price_complete,
                has_unpriced_items=has_unpriced,
            )
        )
    return result


def build_category_breakdown(items: Sequence[PlanItemSchema]) -> list[PlanCategoryBreakdownItem]:
    """Строит предметный разрез бюджета по товарным категориям."""
    groups: dict[str, list[PlanItemSchema]] = defaultdict(list)
    for it in items:
        groups[it.category].append(it)

    result: list[PlanCategoryBreakdownItem] = []
    for cat in sorted(groups.keys()):
        cat_items = groups[cat]
        items_count = len(cat_items)
        total_qty = sum((it.quantity for it in cat_items), ZERO_QTY).quantize(
            QTY_QUANT, rounding=ROUND_HALF_UP
        )
        known_total = sum(
            (it.total_cost for it in cat_items if it.total_cost is not None),
            ZERO_PRICE,
        ).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
        unpriced_count = sum(1 for it in cat_items if it.total_cost is None)
        is_price_complete = unpriced_count == 0
        has_unpriced = unpriced_count > 0

        result.append(
            PlanCategoryBreakdownItem(
                category=cat,
                known_total=known_total,
                total_cost=known_total,
                total_quantity=total_qty,
                items_count=items_count,
                unknown_price_count=unpriced_count,
                unpriced_items_count=unpriced_count,
                is_price_complete=is_price_complete,
                has_unpriced_items=has_unpriced,
            )
        )
    return result


def build_location_breakdown(
    items: Sequence[PlanItemSchema],
    location_names: dict[str, str] | None = None,
) -> list[PlanLocationBreakdownItem]:
    """Строит предметный разрез бюджета по объектам/складам."""
    groups: dict[str, list[PlanItemSchema]] = defaultdict(list)
    for it in items:
        groups[it.location].append(it)

    result: list[PlanLocationBreakdownItem] = []
    for loc in sorted(groups.keys()):
        loc_items = groups[loc]
        items_count = len(loc_items)
        total_qty = sum((it.quantity for it in loc_items), ZERO_QTY).quantize(
            QTY_QUANT, rounding=ROUND_HALF_UP
        )
        known_total = sum(
            (it.total_cost for it in loc_items if it.total_cost is not None),
            ZERO_PRICE,
        ).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
        unpriced_count = sum(1 for it in loc_items if it.total_cost is None)
        is_price_complete = unpriced_count == 0
        has_unpriced = unpriced_count > 0

        name = (location_names.get(loc) if location_names else None) or loc_items[0].location_name

        result.append(
            PlanLocationBreakdownItem(
                location=loc,
                name=name,
                known_total=known_total,
                total_cost=known_total,
                total_quantity=total_qty,
                items_count=items_count,
                unknown_price_count=unpriced_count,
                unpriced_items_count=unpriced_count,
                is_price_complete=is_price_complete,
                has_unpriced_items=has_unpriced,
            )
        )
    return result
