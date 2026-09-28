"""Стандартизированные константы и коды предупреждений для плана закупок."""

WARN_ORDER_DELAYED = (
    "ORDER_DELAYED: Заказ поставщику задержан и исключён из покрытия до переноса даты"
)
WARN_TEMPORARY_DEFICIT = (
    "TEMPORARY_DEFICIT: Потребность возникает раньше возможного поступления; "
    "рекомендуется немедленный заказ"
)
WARN_LEAD_TIME_UNKNOWN = (
    "LEAD_TIME_UNKNOWN: Срок поставки не задан, дата заказа не может быть определена"
)
WARN_NO_DEMAND_HISTORY = (
    "NO_DEMAND_HISTORY: Потребление за 90 дней отсутствует, закупка не рекомендуется"
)
WARN_PRICE_UNKNOWN = "PRICE_UNKNOWN: Цена не указана, расчёт стоимости невозможен"
WARN_DELIVERY_BEYOND_HORIZON = (
    "DELIVERY_BEYOND_HORIZON: Ближайшая возможная поставка позднее конца горизонта; "
    "потребность не обеспечена"
)
WARN_INCOMPLETE_HISTORY = "INCOMPLETE_HISTORY: История движений неполная"
