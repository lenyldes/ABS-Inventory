# Демонстрационный пример плана закупок и бюджета

Документ содержит проверенный сквозной пример запроса и ответа эндпоинта `POST /api/procurement/plan` на синтетическом демонстрационном наборе данных (`tests/test_api_procurement_plan_e2e.py`).

## 1. Контекст демонстрационных данных

- **Склады**: `LOC-MSK` (Москва), `LOC-SPB` (СПб).
- **Товары**:
  - `SKU-OIL` (Масло): расход 10 л/д, остаток 100 л, плечо 5 дн., упак. 10 л, мин. 20 л, цена 100.00 руб.
  - `SKU-CRM` (Крем): расход 5 шт/д, остаток 10 шт, плечо 7 дн., упак. 5 шт, мин. 10 шт, цена 200.00 руб.
  - `SKU-GEL` (Гель): расход 2 шт/д, остаток 0 шт, плечо 10 дн., упак. 12 шт, мин. 24 шт, цена 150.00 руб.
- **Оформленные заказы** (`incoming_orders`, исключены из новых затрат):
  - `PO-OIL-MSK-01`: 100 л на 2026-09-21, цена 100.00 руб.
  - `PO-GEL-MSK-01`: 60 шт на 2026-09-16, цена 150.00 руб.

---

## 2. Запрос API

```http
POST /api/procurement/plan HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "as_of": "2026-09-15",
  "horizon_months": 3,
  "service_days": 3,
  "budget_limit": "500000.00"
}
```

---

## 3. Ответ API (200 OK)

```json
{
  "as_of": "2026-09-15",
  "horizon_months": 3,
  "service_days": 3,
  "location": null,
  "category": null,
  "budget_limit": "500000.00",
  "horizon_start": "2026-09-16",
  "horizon_end": "2026-12-15",
  "days_count": 91,
  "is_first_month_partial": true,
  "is_last_month_partial": true,
  "items": [
    {
      "sku": "SKU-GEL", "category": "Гели", "location": "LOC-MSK", "supplier": "SUP-2",
      "order_date": "2026-10-03", "delivery_date": "2026-10-13", "quantity": "72.000", "unit_price": "150.00", "total_cost": "10800.00",
      "metrics": {"initial_stock": "0.000", "incoming_orders": "60.000", "expected_orders_qty": "60.000", "average_daily_consumption": "2.000000", "safety_stock": "6.000"},
      "warnings": []
    },
    {
      "sku": "SKU-GEL", "category": "Гели", "location": "LOC-MSK", "supplier": "SUP-2",
      "order_date": "2026-11-08", "delivery_date": "2026-11-18", "quantity": "60.000", "unit_price": "150.00", "total_cost": "9000.00",
      "metrics": {"initial_stock": "0.000", "incoming_orders": "60.000", "expected_orders_qty": "60.000", "average_daily_consumption": "2.000000", "safety_stock": "6.000"},
      "warnings": []
    },
    {
      "sku": "SKU-OIL", "category": "Масла", "location": "LOC-MSK", "supplier": "SUP-1",
      "order_date": "2026-09-28", "delivery_date": "2026-10-03", "quantity": "320.000", "unit_price": "100.00", "total_cost": "32000.00",
      "metrics": {"initial_stock": "100.000", "incoming_orders": "100.000", "expected_orders_qty": "100.000", "average_daily_consumption": "10.000000", "safety_stock": "30.000"},
      "warnings": []
    },
    {
      "sku": "SKU-OIL", "category": "Масла", "location": "LOC-MSK", "supplier": "SUP-1",
      "order_date": "2026-10-30", "delivery_date": "2026-11-04", "quantity": "310.000", "unit_price": "100.00", "total_cost": "31000.00",
      "metrics": {"initial_stock": "100.000", "incoming_orders": "100.000", "expected_orders_qty": "100.000", "average_daily_consumption": "10.000000", "safety_stock": "30.000"},
      "warnings": []
    },
    {
      "sku": "SKU-OIL", "category": "Масла", "location": "LOC-MSK", "supplier": "SUP-1",
      "order_date": "2026-11-30", "delivery_date": "2026-12-05", "quantity": "110.000", "unit_price": "100.00", "total_cost": "11000.00",
      "metrics": {"initial_stock": "100.000", "incoming_orders": "100.000", "expected_orders_qty": "100.000", "average_daily_consumption": "10.000000", "safety_stock": "30.000"},
      "warnings": []
    },
    {
      "sku": "SKU-CRM", "category": "Кремы", "location": "LOC-SPB", "supplier": "SUP-1",
      "order_date": "2026-09-15", "delivery_date": "2026-09-22", "quantity": "170.000", "unit_price": "200.00", "total_cost": "34000.00",
      "metrics": {"initial_stock": "10.000", "incoming_orders": "0.000", "expected_orders_qty": "0.000", "average_daily_consumption": "5.000000", "safety_stock": "15.000", "deficit_start": "2026-09-18", "deficit_delivery_date": "2026-09-22"},
      "warnings": [
        "TEMPORARY_DEFICIT: Потребность возникает раньше возможного поступления; дефицит с 2026-09-16 до 2026-09-22; рекомендуется немедленный заказ"
      ]
    },
    {
      "sku": "SKU-CRM", "category": "Кремы", "location": "LOC-SPB", "supplier": "SUP-1",
      "order_date": "2026-10-16", "delivery_date": "2026-10-23", "quantity": "160.000", "unit_price": "200.00", "total_cost": "32000.00",
      "metrics": {"initial_stock": "10.000", "incoming_orders": "0.000", "expected_orders_qty": "0.000", "average_daily_consumption": "5.000000", "safety_stock": "15.000"},
      "warnings": []
    },
    {
      "sku": "SKU-CRM", "category": "Кремы", "location": "LOC-SPB", "supplier": "SUP-1",
      "order_date": "2026-11-17", "delivery_date": "2026-11-24", "quantity": "110.000", "unit_price": "200.00", "total_cost": "22000.00",
      "metrics": {"initial_stock": "10.000", "incoming_orders": "0.000", "expected_orders_qty": "0.000", "average_daily_consumption": "5.000000", "safety_stock": "15.000"},
      "warnings": []
    }
  ],
  "existing_orders": [
    {"order_id": 528, "doc_number": "PO-GEL-MSK-01", "sku": "SKU-GEL", "location": "LOC-MSK", "expected_date": "2026-09-16", "pending_qty": "60.000", "unit_price": "150.00", "supplier_id": "SUP-2"},
    {"order_id": 527, "doc_number": "PO-OIL-MSK-01", "sku": "SKU-OIL", "location": "LOC-MSK", "expected_date": "2026-09-21", "pending_qty": "100.000", "unit_price": "100.00", "supplier_id": "SUP-1"}
  ],
  "budget": {
    "known_total": "181800.00", "total_quantity": "1312.000", "is_price_complete": true, "is_dates_complete": true, "undated_count": 0,
    "by_month": [
      {"month": "2026-09", "known_total": "66000.00", "total_quantity": "490.000", "items_count": 2, "is_partial": true},
      {"month": "2026-10", "known_total": "73800.00", "total_quantity": "542.000", "items_count": 3, "is_partial": false},
      {"month": "2026-11", "known_total": "42000.00", "total_quantity": "280.000", "items_count": 3, "is_partial": false},
      {"month": "2026-12", "known_total": "0.00", "total_quantity": "0.000", "items_count": 0, "is_partial": true}
    ],
    "undated": {"known_total": "0.00", "total_quantity": "0.000", "items_count": 0},
    "by_sku": [
      {"sku": "SKU-CRM", "known_total": "88000.00", "total_quantity": "440.000", "items_count": 3},
      {"sku": "SKU-GEL", "known_total": "19800.00", "total_quantity": "132.000", "items_count": 2},
      {"sku": "SKU-OIL", "known_total": "74000.00", "total_quantity": "740.000", "items_count": 3}
    ],
    "by_category": [
      {"category": "Гели", "known_total": "19800.00", "total_quantity": "132.000", "items_count": 2},
      {"category": "Кремы", "known_total": "88000.00", "total_quantity": "440.000", "items_count": 3},
      {"category": "Масла", "known_total": "74000.00", "total_quantity": "740.000", "items_count": 3}
    ],
    "by_location": [
      {"location": "LOC-MSK", "known_total": "93800.00", "total_quantity": "872.000", "items_count": 5},
      {"location": "LOC-SPB", "known_total": "88000.00", "total_quantity": "440.000", "items_count": 3}
    ],
    "budget_limit": "500000.00", "limit_status": "within", "limit_difference": "-318200.00"
  },
  "explanation": {
    "data_used": [
      {"name": "as_of", "value": "2026-09-15", "source": "Параметр: дата актуальности"},
      {"name": "known_total_cost", "value": "181800.00", "source": "Стоимость плана"},
      {"name": "total_items_count", "value": 8, "source": "Количество позиций плана"},
      {"name": "existing_orders_count", "value": 2, "source": "Количество оформленных заказов"},
      {"name": "limit_status", "value": "within", "source": "Статус соблюдения лимита"},
      {"name": "limit_difference", "value": "-318200.00", "source": "Разница с лимитом бюджета"}
    ],
    "formulas": [
      "FEFO: списание партий с минимальным сроком годности в первую очередь.",
      "Страховой запас: safety_stock = round(average_daily_consumption * service_days, 3).",
      "Месячная цель: объём покрывает расход до min(приход + 1 месяц, конец горизонта) + страховой запас.",
      "Кванты поставки: округление вверх до min_order_qty и целого числа упаковок (package_size)."
    ],
    "assumptions": [
      "Лимит бюджета носит информационный характер: состав и объём рекомендаций не обрезаются.",
      "Оформленные ранее заказы поставщикам учитываются как входные поставки и исключены из стоимости новых рекомендаций."
    ],
    "incompleteness_reasons": [
      "Временный дефицит: потребность возникает до даты ближайшего возможного поступления заказа."
    ]
  },
  "warnings": [
    "INCOMPLETE_HISTORY: История движений неполная (0 дн. из 90)",
    "NO_DEMAND_HISTORY: Потребление за 90 дней отсутствует, закупка не рекомендуется",
    "TEMPORARY_DEFICIT: Потребность возникает раньше возможного поступления; дефицит с 2026-09-16 до 2026-09-22; рекомендуется немедленный заказ"
  ]
}
```

---

## 4. Сверка арифметики и разрезов бюджета

1. **Сумма всех 8 позиций плана**:
   - GEL-1 (10800) + GEL-2 (9000) + OIL-1 (32000) + OIL-2 (31000) + OIL-3 (11000) + CRM-1 (34000) + CRM-2 (32000) + CRM-3 (22000) = **181800.00 руб.**
   - Количество: `72 + 60 + 320 + 310 + 110 + 170 + 160 + 110 = 1312.000 шт/л`.
2. **Календарный разрез**: `66000.00 (сен) + 73800.00 (окт) + 42000.00 (ноя) + 0.00 (дек) + 0.00 (undated) = 181800.00 руб.`
3. **Разрез по SKU**: `88000.00 (CRM) + 19800.00 (GEL) + 74000.00 (OIL) = 181800.00 руб.`
4. **Разрез по категориям**: `19800.00 (Гели) + 88000.00 (Кремы) + 74000.00 (Масла) = 181800.00 руб.`
5. **Разрез по складам**: `93800.00 (LOC-MSK) + 88000.00 (LOC-SPB) = 181800.00 руб.`
6. **Лимит**: `181800.00 <= 500000.00` -> статус `within`, разница `-318200.00 руб.`
