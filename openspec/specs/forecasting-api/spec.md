# forecasting-api Specification

## Purpose
Определить публичный контракт прогноза потребности и закупки: входные параметры, состав ответа, объяснение расчёта и ошибки API.

## Requirements

### Requirement: Семантика полей и контракт POST `/api/forecast`
POST `/api/forecast` SHALL рассчитывать показатели потребности и закупки:
- **Вход JSON**: `sku` (str, обязательное), `location` (str, обязательное), `as_of` (date, def today), `horizon_days` (int $\ge 1$, взаимоисключающий с `horizon_months`), `horizon_months` (int $\ge 1$, взаимоисключающий с `horizon_days`), `service_days` (int $\ge 0$, def 0).
- **Ответ 200 OK**:
  - `sku`, `location`, `as_of`, `horizon_start` (`as_of + 1`), `horizon_end`, `days_count`;
  - `average_daily_consumption` (Decimal(12,6)), `forecast_consumption` (Decimal(12,3), $a \times D$), `safety_stock` (Decimal(12,3), $a \times S$), `current_stock` (Decimal(12,3), физический остаток на `as_of`), `available_stock` (Decimal(12,3), годный остаток на `as_of`), `incoming_qty` (Decimal(12,3), ожидаемые поставки $t > as\_of$);
  - `stockout_date` (date|null, первая дата нулевого остатка), `order_date` (date|null), `reorder_point` (Decimal(12,3)|null), `recommended_qty` (Decimal(12,3)), `unit_price` (Decimal(12,2)|null), `total_cost` (Decimal(12,2)|null);
  - `is_history_complete` (bool), `history_days` (int), `daily_forecast` (`[{"date": date, "consumption": Decimal, "incoming": Decimal, "expired": Decimal, "closing_stock": Decimal, "daily_deficit": Decimal}]`), `explanation` (object), `warnings` (list[str]).
  Объект `explanation` SHALL содержать `data_used` (список исходных показателей с их значениями и источниками), `formulas` (список применённых формул) и `assumptions` (список допущений и ограничений). Он SHALL объяснять 90-дневное окно, возвраты, выбранный горизонт, остатки, ожидаемые поставки, условия и источник цены, а также округление, если соответствующие данные участвуют в расчёте. Недоступные показатели передаются как `null`, а не как нули.
- **Ошибки**: `400` (не задан или заданы оба горизонта, неположительный горизонт, отрицательный `service_days`), `404` (SKU или объект не найден), `422` (невалидный формат даты/типов).

#### Scenario: Позднее исправление
- **WHEN** после исправления поступления повторно рассчитывается тот же прошлый период
- **THEN** результат отражает исправленную историю и может отличаться от прежнего ответа.

#### Scenario: Ошибки параметров прогноза
- **WHEN** переданы одновременно `horizon_days` и `horizon_months` или передан неизвестный SKU
- **THEN** система возвращает соответственно `400 Bad Request` и `404 Not Found`.

#### Scenario: Проверяемое объяснение
- **WHEN** расчёт использует расход за 90 дней, остаток двух партий, ожидаемую поставку и ориентировочную цену
- **THEN** `explanation.data_used` показывает эти значения и их источники, `formulas` описывает вычисление объёма, а `assumptions` сообщает об использовании ориентировочной цены и годности будущей поставки.
