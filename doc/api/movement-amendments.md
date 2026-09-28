# Контракты API исправлений и аудита

1. **POST `/api/amendments/preview`** — предварительная симуляция набора правок:
   - **Вход JSON**: `reason` (str, обязательное), `operations` (list):
     - `movement_id` (int, обязательное);
     - `action` (`update`|`cancel`, обязательное);
     - `expected_version` (int, версия записи);
     - `fields` (object, для `update`: опциональные `quantity` всего движения, `operation_date`, `doc_number`, `allocation_id` вместе с новым `batch_id` для смены партии одной строки расхода, `location`; `sku` менять запрещено). При изменении `quantity` расхода обязателен `allocation_quantities`: список объектов `{ "allocation_id": int, "quantity": decimal }` для строк, количество которых меняется.
   - **Ответ 200 OK**:
     ```json
     {
       "preview_id": "c1f7a4e2-892b-4e4b-9721-3a0172e9d001",
       "version_signature": "sig_a78fbc3190",
       "can_apply": true,
       "stock_impact": [
         {
           "sku": "OIL-500",
           "location": "MSK-01",
           "batch_id": 12,
           "current_stock_before": "20.000",
           "current_stock_after": "2.000",
           "available_stock_before": "20.000",
           "available_stock_after": "2.000"
         }
       ],
       "affected_operations": [],
       "blockers": []
     }
     ```
   - **Ошибки**: `400` (пустой список операций или нет причины), `404` (`movement_id` не найден), `422` (попытка смены `sku`, некорректные поля).

2. **POST `/api/amendments/confirm`** — атомарное подтверждение набора:
   - **Вход JSON**: `preview_id` (str, обязательное), `version_signature` (str, обязательное), `reason` (str, обязательное).
   - **Поведение и защита от гонок**:
     - Блокирует затронутые пары «товар + объект» в транзакции.
     - Если с момента вызова preview появились новые движения по этим парам или изменились версии затронутых операций — система возвращает `409 Conflict` (`stale_preview`) без применения изменений.
     - Если при расчёте выявлены блокирующие нарушения — возвращает `422 Unprocessable Entity` (`dependency_violation`).
     - При успехе — атомарно фиксирует изменения, сохраняет версии в аудите и возвращает `200 OK`:
       ```json
       {
         "status": "applied",
         "amendment_id": "amend-20260928-001",
         "applied_movements": [{"movement_id": 101, "version": 2, "action": "update"}]
       }
       ```

3. **GET `/api/movements/{id}/history`** — аудит изменений движения:
   - **Path**: `id` (int).
   - **Ответ 200 OK**:
     ```json
     {
       "movement_id": 101,
       "is_cancelled": false,
       "current_state": {"quantity": "2.000", "doc_number": "DOC-101"},
       "versions": [
         {"version_num": 1, "created_at": "2026-09-28T10:00:00Z", "action": "create", "reason": "Первичный ввод", "changes": {}},
         {"version_num": 2, "created_at": "2026-09-28T11:00:00Z", "action": "update", "reason": "Опечатка в количестве", "changes": {"quantity": {"old": "20.000", "new": "2.000"}}}
       ]
     }
     ```
   - **Ошибки**: `404 Not Found`.
