# Примеры API-запросов и работа с сервисом

В данном документе приведены практические примеры взаимодействия с REST API сервиса **ABS Inventory & Procurement Assistant** с использованием утилит `curl` и `jq`.

Все запросы можно выполнять как локально (`http://localhost:8000`), так и на публичном демонстрационном стенде (`https://abs-inventory.lenyldes.ru`).

---

## 1. Системные эндпоинты

### Проверка работоспособности сервиса и БД
```bash
curl -s http://localhost:8000/health | jq .
```
**Ответ (200 OK):**
```json
{
  "status": "healthy",
  "database": "available"
}
```

### Статус демонстрационных данных
```bash
curl -s http://localhost:8000/api/demo/status | jq .
```

---

## 2. Складской учёт и остатки

### Получение текущих остатков склада
Возвращает остатки по товарам и объектам с расчётом среднего расхода за 90 дней, запаса в днях и ближайшего срока годности:
```bash
curl -s "http://localhost:8000/api/stock?as_of=2026-09-29" | jq .
```

### Детализация остатков по позициям и партиям
Возвращает разбивку конкретного SKU по объектам хранения и партиям:
```bash
curl -s "http://localhost:8000/api/stock/DEMO-OIL?as_of=2026-09-29" | jq .
```

### История складских движений (Журнал)
Постраничный просмотр с фильтрацией:
```bash
curl -s "http://localhost:8000/api/movements?sku=DEMO-OIL&limit=10&offset=0" | jq .
```

---

## 3. Регистрация движений (POST /api/movements)

### Регистрация расхода по правилу FEFO
Система автоматически списывает количество с партий с ближайшим сроком годности:
```bash
curl -s -X POST "http://localhost:8000/api/movements" \
  -H "Content-Type: application/json" \
  -d '{
    "operation_date": "2026-09-29",
    "sku": "DEMO-OIL",
    "location": "DEMO-MS-01",
    "type": "consume",
    "quantity": 5.0,
    "doc_number": "CONSUME-CURL-001"
  }' | jq .
```

### Регистрация поступления новой партии
```bash
curl -s -X POST "http://localhost:8000/api/movements" \
  -H "Content-Type: application/json" \
  -d '{
    "operation_date": "2026-09-29",
    "sku": "DEMO-OIL",
    "location": "DEMO-MS-01",
    "type": "receipt",
    "quantity": 20.0,
    "batch": {
      "batch_number": "B-CURL-999",
      "expiry_date": "2027-06-30",
      "unit_price": 1250.00
    },
    "doc_number": "RECEIPT-CURL-001"
  }' | jq .
```

---

## 4. Прогнозирование и риски

### Расчёт потребности в закупке (POST /api/forecast)
```bash
curl -s -X POST "http://localhost:8000/api/forecast" \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "DEMO-OIL",
    "location": "DEMO-MS-01",
    "horizon_months": 3,
    "service_days": 14
  }' | jq .
```

### Предупреждения по складу (GET /api/alerts)
Выявление рисков дефицита, истечения срока годности и залежавшихся остатков:
```bash
curl -s "http://localhost:8000/api/alerts?as_of=2026-09-29" | jq .
```

---

## 5. Планирование закупок и бюджет

### Расчёт сводного плана закупок и бюджета (POST /api/procurement/plan)
```bash
curl -s -X POST "http://localhost:8000/api/procurement/plan" \
  -H "Content-Type: application/json" \
  -d '{
    "horizon_months": 3,
    "service_days": 14,
    "budget_limit": 500000.00
  }' | jq .
```
