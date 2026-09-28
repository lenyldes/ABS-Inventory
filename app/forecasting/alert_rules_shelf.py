"""Правила оценки сроков годности, просрочки и риска списания партий."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.forecasting.domain import AlertItem
from app.inventory.domain import BatchStock


def evaluate_shelf_life_alerts(
    sku: str,
    location: str,
    as_of: date,
    batches: Sequence[BatchStock],
    shelf_life_days_threshold: int,
    total_expired_forecast: Decimal,
    effective_horizon_days: int,
    horizon_end: date,
    calculation_limit: str | None = None,
) -> list[AlertItem]:
    """Формирует предупреждения о просрочке, приближении срока и риске списания."""
    alerts: list[AlertItem] = []

    # Просроченные партии (critical)
    for bs in sorted(batches, key=lambda b: (b.expiry_date or date.min, b.batch_id)):
        has_qty = bs.current_quantity > Decimal("0")
        is_exp = bs.expiry_date is not None and bs.expiry_date < as_of
        if has_qty and is_exp:
            assert bs.expiry_date is not None
            days_overdue = (as_of - bs.expiry_date).days
            alerts.append(
                AlertItem(
                    id=f"alert-expired-{location}-{sku}-{bs.batch_id}-{as_of.isoformat()}",
                    type="expired",
                    level="critical",
                    sku=sku,
                    location=location,
                    batch_id=bs.batch_id,
                    message=(
                        f"Просроченный остаток: срок годности партии {bs.batch_number} "
                        f"истёк {days_overdue} дн. назад"
                    ),
                    metrics={
                        "batch_id": bs.batch_id,
                        "batch_number": bs.batch_number,
                        "current_quantity": str(bs.current_quantity),
                        "expired_quantity": str(bs.expired_quantity),
                        "expiry_date": bs.expiry_date.isoformat(),
                        "days_overdue": days_overdue,
                    },
                    as_of=as_of,
                )
            )

    # Приближение срока годности (warning)
    for bs in sorted(batches, key=lambda b: (b.expiry_date or date.max, b.batch_id)):
        has_avail = bs.available_quantity > Decimal("0")
        is_valid = bs.expiry_date is not None and bs.expiry_date >= as_of
        if has_avail and is_valid:
            assert bs.expiry_date is not None
            days_until_expiry = (bs.expiry_date - as_of).days
            if 0 <= days_until_expiry <= shelf_life_days_threshold:
                alerts.append(
                    AlertItem(
                        id=f"alert-expiring_soon-{location}-{sku}-{bs.batch_id}-{as_of.isoformat()}",
                        type="expiring_soon",
                        level="warning",
                        sku=sku,
                        location=location,
                        batch_id=bs.batch_id,
                        message=(
                            f"Приближение срока годности: у партии {bs.batch_number} "
                            f"осталось {days_until_expiry} дн. до истечения срока"
                        ),
                        metrics={
                            "batch_id": bs.batch_id,
                            "batch_number": bs.batch_number,
                            "available_quantity": str(bs.available_quantity),
                            "expiry_date": bs.expiry_date.isoformat(),
                            "days_until_expiry": days_until_expiry,
                            "shelf_life_days_threshold": shelf_life_days_threshold,
                        },
                        as_of=as_of,
                    )
                )

    # Риск списания по FEFO (warning)
    if total_expired_forecast > Decimal("0"):
        alerts.append(
            AlertItem(
                id=f"alert-writeoff_risk-{location}-{sku}-{as_of.isoformat()}",
                type="writeoff_risk",
                level="warning",
                sku=sku,
                location=location,
                batch_id=None,
                message=(
                    f"Риск списания по сроку годности: ожидается списание "
                    f"{total_expired_forecast} ед. на горизонте прогноза"
                ),
                metrics={
                    "expected_writeoff_qty": str(total_expired_forecast.quantize(Decimal("0.001"))),
                    "horizon_days": effective_horizon_days,
                    "horizon_end": horizon_end.isoformat(),
                    **({"calculation_limit": calculation_limit} if calculation_limit else {}),
                },
                as_of=as_of,
            )
        )

    return alerts
