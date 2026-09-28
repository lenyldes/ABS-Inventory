"""Модуль расчёта плана повторных закупок и бюджета."""

from app.procurement.rounding import (
    PRICE_QUANT,
    QTY_QUANT,
    ZERO_PRICE,
    ZERO_QTY,
    calculate_total_cost,
    round_order_quantity,
    round_unit_price,
)
from app.procurement_plan.breakdowns import (
    build_category_breakdown,
    build_location_breakdown,
    build_monthly_breakdown,
    build_procurement_plan_breakdowns,
    build_sku_breakdown,
    build_undated_breakdown,
    evaluate_budget_limit,
)
from app.procurement_plan.dates import (
    add_one_month,
    compute_coverage_interval,
    generate_horizon_months,
)
from app.procurement_plan.domain import PlanDatabaseSnapshot, PlanItemLocationPair
from app.procurement_plan.explanation import (
    build_plan_explanation,
    build_plan_explanation_data_used,
)
from app.procurement_plan.explanation_templates import (
    build_plan_explanation_assumptions,
    build_plan_explanation_formulas,
    get_incompleteness_reasons,
)
from app.procurement_plan.planning import (
    PairPlanResult,
    plan_pair_procurement,
)
from app.procurement_plan.repository import (
    load_catalog_pairs,
    load_plan_database_snapshot,
    set_repeatable_read_snapshot,
)
from app.procurement_plan.snapshot_adapter import plan_pair_from_snapshot
from app.procurement_plan.undated import calculate_undated_item
from app.procurement_plan.warnings import (
    WARN_DELIVERY_BEYOND_HORIZON,
    WARN_INCOMPLETE_HISTORY,
    WARN_LEAD_TIME_UNKNOWN,
    WARN_NO_DEMAND_HISTORY,
    WARN_ORDER_DELAYED,
    WARN_PRICE_UNKNOWN,
    WARN_TEMPORARY_DEFICIT,
)

__all__ = [
    "PRICE_QUANT",
    "QTY_QUANT",
    "WARN_DELIVERY_BEYOND_HORIZON",
    "WARN_INCOMPLETE_HISTORY",
    "WARN_LEAD_TIME_UNKNOWN",
    "WARN_NO_DEMAND_HISTORY",
    "WARN_ORDER_DELAYED",
    "WARN_PRICE_UNKNOWN",
    "WARN_TEMPORARY_DEFICIT",
    "ZERO_PRICE",
    "ZERO_QTY",
    "PairPlanResult",
    "PlanDatabaseSnapshot",
    "PlanItemLocationPair",
    "add_one_month",
    "build_category_breakdown",
    "build_location_breakdown",
    "build_monthly_breakdown",
    "build_plan_explanation",
    "build_plan_explanation_assumptions",
    "build_plan_explanation_data_used",
    "build_plan_explanation_formulas",
    "build_procurement_plan_breakdowns",
    "build_sku_breakdown",
    "build_undated_breakdown",
    "calculate_total_cost",
    "calculate_undated_item",
    "compute_coverage_interval",
    "evaluate_budget_limit",
    "generate_horizon_months",
    "get_incompleteness_reasons",
    "load_catalog_pairs",
    "load_plan_database_snapshot",
    "plan_pair_from_snapshot",
    "plan_pair_procurement",
    "round_order_quantity",
    "round_unit_price",
    "set_repeatable_read_snapshot",
]
