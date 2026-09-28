# Демонстрационный пример плана закупок и бюджета

Документ содержит проверенный сквозной пример запроса и ответа эндпоинта `POST /api/procurement/plan` на синтетическом демонстрационном наборе данных.

## 1. Контекст демонстрационных данных

- **Склады**: `LOC-MSK` («Москва Склад»), `LOC-SPB` («СПб Склад»).
- **Товары**:
  - `SKU-OIL` (Масло): расход 10 л/день, остаток 100 л, плечо 5 дн., упаковка 10 л, мин. 20 л, цена 100.00 руб.
  - `SKU-CRM` (Крем): расход 5 шт/день, остаток 10 шт, плечо 7 дн., упаковка 5 шт, мин. 10 шт, цена 200.00 руб.
  - `SKU-GEL` (Гель): расход 2 шт/день, остаток 0 шт, плечо 10 дн., упаковка 12 шт, мин. 24 шт, цена 150.00 руб.
- **Оформленные ранее заказы**:
  - `PO-OIL-MSK-01`: 100 л, ожидается 2026-09-21, цена 100.00 руб.
  - `PO-GEL-MSK-01`: 60 шт, ожидается 2026-09-16, цена 150.00 руб.

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
      "sku": "SKU-OIL",
      "category": "Масла",
      "location": "LOC-MSK",
      "supplier": "Поставщик Альфа",
      "order_date": "2026-09-28",
      "delivery_date": "2026-10-03",
      "coverage_start": "2026-10-03",
      "coverage_end": "2026-11-03",
      "quantity": "320.000",
      "unit_price": "100.00",
      "price_source": "estimated",
      "total_cost": "32000.00",
      "warnings": []
    },
    {
      "sku": "SKU-OIL",
      "category": "Масла",
      "location": "LOC-MSK",
      "supplier": "Поставщик Альфа",
      "order_date": "2026-10-30",
      "delivery_date": "2026-11-04",
      "coverage_start": "2026-11-04",
      "coverage_end": "2026-12-04",
      "quantity": "310.000",
      "unit_price": "100.00",
      "price_source": "estimated",
      "total_cost": "31000.00",
      "warnings": []
    },
    {
      "sku": "SKU-OIL",
      "category": "Масла",
      "location": "LOC-MSK",
      "supplier": "Поставщик Альфа",
      "order_date": "2026-11-30",
      "delivery_date": "2026-12-05",
      "coverage_start": "2026-12-05",
      "coverage_end": "2026-12-15",
      "quantity": "110.000",
      "unit_price": "100.00",
      "price_source": "estimated",
      "total_cost": "11000.00",
      "warnings": []
    },
    {
      "sku": "SKU-CRM",
      "category": "Кремы",
      "location": "LOC-SPB",
      "supplier": "Поставщик Альфа",
      "order_date": "2026-09-15",
      "delivery_date": "2026-09-22",
      "coverage_start": "2026-09-22",
      "coverage_end": "2026-10-22",
      "quantity": "170.000",
      "unit_price": "200.00",
      "price_source": "estimated",
      "total_cost": "34000.00",
      "warnings": [
        "TEMPORARY_DEFICIT: Потребность возникает раньше возможного поступления; рекомендуется немедленный заказ"
      ]
    },
    {
      "sku": "SKU-GEL",
      "category": "Гели",
      "location": "LOC-MSK",
      "supplier": "Поставщик Бета",
      "order_date": "2026-10-03",
      "delivery_date": "2026-10-13",
      "coverage_start": "2026-10-13",
      "coverage_end": "2026-11-13",
      "quantity": "72.000",
      "unit_price": "150.00",
      "price_source": "estimated",
      "total_cost": "10800.00",
      "warnings": []
    }
  ],
  "existing_orders": [
    {
      "order_id": 528,
      "doc_number": "PO-GEL-MSK-01",
      "sku": "SKU-GEL",
      "location": "LOC-MSK",
      "expected_date": "2026-09-16",
      "pending_qty": "60.000",
      "unit_price": "150.00",
      "supplier_name": "Поставщик Бета"
    },
    {
      "order_id": 527,
      "doc_number": "PO-OIL-MSK-01",
      "sku": "SKU-OIL",
      "location": "LOC-MSK",
      "expected_date": "2026-09-21",
      "pending_qty": "100.000",
      "unit_price": "100.00",
      "supplier_name": "Поставщик Альфа"
    }
  ],
  "budget": {
    "known_total": "181800.00",
    "total_quantity": "1312.000",
    "is_price_complete": true,
    "is_dates_complete": true,
    "undated_count": 0,
    "by_month": [
      {"month": "2026-09", "year": 2026, "month_number": 9, "known_total": "66000.00", "total_quantity": "490.000", "items_count": 2, "is_partial": true},
      {"month": "2026-10", "year": 2026, "month_number": 10, "known_total": "73800.00", "total_quantity": "542.000", "items_count": 3, "is_partial": false},
      {"month": "2026-11", "year": 2026, "month_number": 11, "known_total": "42000.00", "total_quantity": "280.000", "items_count": 3, "is_partial": false},
      {"month": "2026-12", "year": 2026, "month_number": 12, "known_total": "0.00", "total_quantity": "0.000", "items_count": 0, "is_partial": true}
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
    "budget_limit": "500000.00",
    "limit_status": "within",
    "limit_difference": "-318200.00"
  },
  "explanation": {
    "data_used": [
      {"name": "as_of", "value": "2026-09-15", "source": "Параметр запроса: контрольная дата актуальности расчёта"},
      {"name": "horizon_dates", "value": "2026-09-16 .. 2026-12-15", "source": "Расчёт: календарный интервал скользящего горизонта потребности"},
      {"name": "known_total_cost", "value": "181800.00", "source": "Расчёт: суммарная известная стоимость рекомендуемых заказов плана"},
      {"name": "existing_orders_count", "value": 2, "source": "БД: количество оформленных неполученных заказов, учтённых как входные поставки"},
      {"name": "limit_status", "value": "within", "source": "Расчёт: статус соблюдения лимита бюджета (within, exceeded, undetermined)"},
      {"name": "limit_difference", "value": "-318200.00", "source": "Расчёт: разница известной стоимости и лимита бюджета"}
    ],
    "formulas": [
      "FEFO: посуточное списание партий с наиболее ранним сроком годности в первую очередь.",
      "Страховой запас: safety_stock = round(average_daily_consumption * service_days, 3).",
      "Месячная цель пополнения: объём покрывает расход до min(дата прихода + 1 месяц, конец горизонта) + страховой запас.",
      "Кванты поставки: округление вверх до min_order_qty и кратно package_size."
    ],
    "assumptions": [
      "Лимит бюджета носит информационный характер: позиции плана не обрезаются.",
      "Оформленные ранее заказы поставщикам учитываются как входные поставки и исключены из стоимости новых рекомендаций."
    ],
    "incompleteness_reasons": [
      "Временный дефицит: потребность возникает до даты ближайшего возможного поступления заказа."
    ]
  },
  "warnings": [
    "TEMPORARY_DEFICIT: Потребность возникает раньше возможного поступления; рекомендуется немедленный заказ"
  ]
}
```

---

## 4. Сверка арифметики и разрезов бюджета

1. **Сумма всех 8 позиций**:
   - Стоимость: `32000 + 31000 + 11000 + 34000 + 32000 + 22000 + 10800 + 9000 = 181800.00 руб.`
   - Количество: `320 + 310 + 110 + 170 + 160 + 110 + 72 + 60 = 1312.000 шт/л`.
2. **Календарный разрез**: `66000 (сен) + 73800 (окт) + 42000 (ноя) + 0 (дек) + 0 (undated) = 181800.00 руб.`
3. **Разрез по SKU**: `88000 (CRM) + 19800 (GEL) + 74000 (OIL) = 181800.00 руб.`
4. **Разрез по категориям**: `19800 (Гели) + 88000 (Кремы) + 74000 (Масла) = 181800.00 руб.`
5. **Разрез по складам**: `93800 (LOC-MSK) + 88000 (LOC-SPB) = 181800.00 руб.`
6. **Лимит**: `181800.00 <= 500000.00` $\implies$ статус `within`, разница `-318200.00 руб.`
