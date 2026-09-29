/** Готовые читающие запросы и извлечение полей из фактических ответов. */
const money = (value) => value ?? "Нет данных";
const line = (label, value) => `${label}: ${money(value)}`;

export function readCases(asOf) {
  const stock = { sku: "DEMO-OIL", location: "DEMO-MS-01", as_of: asOf, limit: 50, offset: 0 };
  return [
    {
      id: "stock", title: "Остаток", goal: "Проверить учётный и доступный остаток масла.",
      steps: () => [{ method: "GET", path: "/api/stock", params: stock, expected: 200,
        summarize(body) {
          const row = body?.items?.find((item) => item.sku === stock.sku && item.location === stock.location);
          return row ? [line("Учётный остаток", row.current_stock), line("Доступный остаток", row.available_stock),
            line("Средний расход в день", row.average_daily_consumption), line("Дни запаса", row.days_of_stock),
            line("Ближайший срок", row.nearest_expiry_date), line("Всего строк", body.total)] : null;
        } }],
    },
    {
      id: "batches", title: "Партии и просрочка", goal: "Показать, почему просроченный остаток недоступен.",
      steps: () => [{ method: "GET", path: "/api/stock/DEMO-EXPIRED",
        params: { location: "DEMO-MS-01", as_of: asOf }, expected: 200,
        summarize(body) {
          const row = body?.locations?.find((item) => item.location === "DEMO-MS-01");
          return row ? [line("Учётный остаток", row.current_stock), line("Доступный остаток", row.available_stock),
            line("Просрочено", row.expired_stock),
            ...row.batches.map((batch) => `Партия #${batch.batch_id}: ${batch.quantity}, срок ${money(batch.expiry_date)}, цена ${money(batch.unit_price)}, документ ${batch.receipt_doc_number}`)] : null;
        } }],
    },
    {
      id: "journal", title: "Журнал", goal: "Проверить фильтры, пагинацию и FEFO-распределения.",
      steps: (offset = 0) => [{ method: "GET", path: "/api/movements",
        params: { sku: "DEMO-OIL", location: "DEMO-MS-01", date_to: asOf, limit: 2, offset }, expected: 200,
        summarize(body) {
          if (!Array.isArray(body?.items) || body.items.length !== 2 || body.total <= 2 ||
              body.limit !== 2 || body.offset !== offset) return null;
          return [line("Строк на странице", body.items.length), line("Всего", body.total),
            line("Смещение", body.offset), ...body.items.map((item) =>
              `${item.doc_number}: ${item.type} ${item.quantity}; распределения: ${item.allocations.map((a) => `#${a.batch_id} ${a.quantity}`).join(", ") || "нет"}; FEFO: ${item.warnings?.map((warning) => warning.message).join(", ") || "нет"}`)];
        } }],
    },
    {
      id: "forecast", title: "Прогноз", goal: "Проверить потребность и стоимость закупки масла.",
      steps: () => [{ method: "POST", path: "/api/forecast", body: {
        sku: "DEMO-OIL", location: "DEMO-MS-01", as_of: asOf, horizon_months: 3,
      }, expected: 200,
      summarize(body) {
        if (body?.sku !== "DEMO-OIL" || body?.location !== "DEMO-MS-01") return null;
        return Object.entries({ "Остаток": body.current_stock, "Средний расход в день": body.average_daily_consumption,
          "Поставки в пути": body.incoming_qty, "Страховой запас": body.safety_stock,
          "Точка заказа": body.reorder_point, "Рекомендуемое количество": body.recommended_qty,
          "Стоимость": body.total_cost, "Дата заказа": body.order_date }).map(([label, value]) => line(label, value))
          .concat(line("Объяснение", JSON.stringify(body.explanation)), line("Предупреждения", JSON.stringify(body.warnings)));
      } }],
    },
    ...[
      ["stockout", "Риск дефицита", "DEMO-DEFICIT", "DEMO-MS-02", "critical"],
      ["no_movement", "Нет движения", "DEMO-IDLE", "DEMO-MS-01", "info"],
    ].map(([type, title, sku, location, level]) => ({
      id: type, title, goal: "Проверить тип, важность и исходные показатели предупреждения.",
      steps: () => [{ method: "GET", path: "/api/alerts",
        params: { sku, location, type, as_of: asOf, limit: 50, offset: 0 }, expected: 200,
        summarize(body) {
          const row = body?.items?.find((item) => item.sku === sku && item.location === location && item.type === type);
          return row && row.level === level
            ? [line("Тип", row.type), line("Важность", row.level), line("Причина", row.message),
              ...Object.entries(row.metrics || {}).map(([key, value]) => line(key, value))] : null;
        } }],
    })),
  ];
}
