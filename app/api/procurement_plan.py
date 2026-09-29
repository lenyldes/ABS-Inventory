"""Маршруты API расчёта плана повторных закупок и бюджета."""

import calendar
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.plan_schemas import (
    PlanItemSchema,
    PlanRequest,
    PlanResponse,
)
from app.core.database import get_db
from app.core.timezone import today_in_moscow
from app.forecasting.domain import compute_horizon_dates
from app.models.catalog import Item, Location
from app.procurement_plan import (
    build_plan_explanation,
    build_procurement_plan_breakdowns,
    load_plan_database_snapshot,
    plan_pair_from_snapshot,
    set_repeatable_read_snapshot,
)

router = APIRouter(prefix="/api/procurement", tags=["Procurement Plan"])

_ALLOWED_HORIZONS = (1, 3, 6, 12)
_ZERO_MONEY = Decimal("0.00")


def _validate_plan_request(req: PlanRequest) -> None:
    """Проверяет допустимость горизонта, неотрицательность дней и лимита бюджета."""
    if req.horizon_months not in _ALLOWED_HORIZONS:
        allowed_str = ", ".join(map(str, _ALLOWED_HORIZONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Параметр horizon_months должен быть одним из: {allowed_str}",
        )
    if req.service_days < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр service_days не может быть отрицательным",
        )
    if req.budget_limit is not None and req.budget_limit < _ZERO_MONEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр budget_limit не может быть отрицательным",
        )


def _validate_filters(db: Session, location_code: str | None, category: str | None) -> None:
    """Проверяет существование объекта и категории в БД при указании фильтров."""
    if location_code is not None:
        loc = db.query(Location).filter(Location.code == location_code).first()
        if loc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Объект '{location_code}' не найден",
            )
    if category is not None:
        cat_exists = db.query(Item).filter(Item.category == category).first()
        if cat_exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Категория '{category}' не найдена",
            )


@router.post(
    "/plan",
    response_model=PlanResponse,
    summary="Расчёт плана повторных закупок и бюджета",
)
def post_procurement_plan(
    req: PlanRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PlanResponse:
    """Вычисляет границы горизонта, планирует закупки и возвращает бюджет с объяснением."""
    _validate_plan_request(req)
    set_repeatable_read_snapshot(db)
    _validate_filters(db, req.location, req.category)

    calc_as_of = req.as_of or today_in_moscow()
    horizon_start, horizon_end, days_count = compute_horizon_dates(
        as_of=calc_as_of,
        horizon_months=req.horizon_months,
    )

    is_first_month_partial = calc_as_of.day != 1
    last_day_of_end_month = calendar.monthrange(horizon_end.year, horizon_end.month)[1]
    is_last_month_partial = horizon_end.day != last_day_of_end_month

    snapshot = load_plan_database_snapshot(
        session=db,
        as_of=calc_as_of,
        location_code=req.location,
        category=req.category,
    )

    all_items: list[PlanItemSchema] = []
    all_warnings: list[str] = []
    seen_warnings: set[str] = set()
    sku_names: dict[str, str] = {}
    sku_categories: dict[str, str] = {}
    location_names: dict[str, str] = {}

    for pair in snapshot.pairs:
        sku_names[pair.item.sku] = pair.item.name
        sku_categories[pair.item.sku] = pair.item.category
        location_names[pair.location.code] = pair.location.name

        pair_result = plan_pair_from_snapshot(
            pair=pair,
            as_of=calc_as_of,
            horizon_months=req.horizon_months,
            service_days=req.service_days,
        )
        all_items.extend(pair_result.items)
        for warn in pair_result.warnings:
            if warn not in seen_warnings:
                seen_warnings.add(warn)
                all_warnings.append(warn)

    budget = build_procurement_plan_breakdowns(
        items=all_items,
        as_of=calc_as_of,
        horizon_months=req.horizon_months,
        horizon_end=horizon_end,
        sku_names=sku_names,
        sku_categories=sku_categories,
        location_names=location_names,
        budget_limit=req.budget_limit,
    )

    explanation = build_plan_explanation(
        as_of=calc_as_of,
        horizon_months=req.horizon_months,
        service_days=req.service_days,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        budget_limit=req.budget_limit,
        items=all_items,
        budget=budget,
        existing_orders=snapshot.existing_orders,
        warnings=all_warnings,
    )

    return PlanResponse(
        as_of=calc_as_of,
        horizon_months=req.horizon_months,
        service_days=req.service_days,
        location=req.location,
        category=req.category,
        budget_limit=req.budget_limit,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        days_count=days_count,
        is_first_month_partial=is_first_month_partial,
        is_last_month_partial=is_last_month_partial,
        items=all_items,
        existing_orders=list(snapshot.existing_orders),
        budget=budget,
        explanation=explanation,
        warnings=all_warnings,
    )
