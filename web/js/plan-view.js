const missing = "Нет данных";
const labels = {
  stockout: "Дефицит", potential_stockout: "Риск дефицита",
  expiring_soon: "Истекает срок", expired: "Просрочено",
  no_movement: "Нет движения", writeoff_risk: "Риск списания",
  incomplete_history: "Неполная история",
  critical: "Критично", warning: "Предупреждение", info: "Информация",
  within: "В пределах лимита", exceeded: "Лимит превышен",
  indeterminate: "Нельзя определить",
};

export function value(data) {
  if (data === null || data === undefined || data === "") return missing;
  if (typeof data === "object") return JSON.stringify(data, null, 2);
  if (typeof data === "boolean") return data ? "Да" : "Нет";
  return labels[data] || String(data);
}

export function element(tag, content, className) {
  const node = document.createElement(tag);
  node.textContent = value(content);
  if (className) node.className = className;
  return node;
}

export function table(headers, rows) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const grid = document.createElement("table");
  const head = grid.createTHead().insertRow();
  headers.forEach((heading) => head.append(element("th", heading)));
  const body = grid.createTBody();
  rows.forEach((row) => {
    const line = body.insertRow();
    row.forEach((cell) => line.append(element("td", cell)));
  });
  wrap.append(grid);
  return wrap;
}

export function section(title, parent) {
  const block = document.createElement("section");
  block.append(element("h3", title));
  parent.append(block);
  return block;
}

export function pairs(parent, entries) {
  const list = document.createElement("dl");
  for (const [label, data] of entries) {
    list.append(element("dt", label), element("dd", data));
  }
  parent.append(list);
}

export function details(parent, title, content) {
  const fold = document.createElement("details");
  fold.append(element("summary", title));
  if (Array.isArray(content)) {
    const list = document.createElement("ul");
    content.forEach((item) => list.append(element("li", item)));
    fold.append(list);
  } else {
    fold.append(element("pre", content));
  }
  parent.append(fold);
}

export function explanation(parent, data, dailyForecast = null) {
  const block = section("Объяснение расчёта", parent);
  details(block, "Исходные данные и источники", data.data_used.map(
    (item) => `${item.name}: ${value(item.value)} (${item.source})`,
  ));
  details(block, "Формулы", data.formulas);
  details(block, "Допущения", data.assumptions);
  if (data.incompleteness_reasons?.length) {
    details(block, "Причины неполноты", data.incompleteness_reasons);
  }
  if (dailyForecast) details(block, "Посуточный прогноз", dailyForecast);
}

function renderBreakdown(parent, title, items, key) {
  const block = section(title, parent);
  block.append(table(
    ["Группа", "Позиций", "Количество", "Известная сумма, ₽", "Без цены", "Цена полная"],
    items.map((item) => [
      key(item), item.items_count, item.total_quantity, item.known_total,
      item.unknown_price_count, item.is_price_complete,
    ]),
  ));
}

export function renderPlan(data) {
  const target = document.querySelector("#plan-result");
  target.replaceChildren();
  const applied = section("Применённые параметры", target);
  pairs(applied, [
    ["Дата снимка", data.as_of], ["Горизонт, месяцев", data.horizon_months],
    ["Период", `${data.horizon_start} — ${data.horizon_end} (${data.days_count} дней)`],
    ["Первый месяц неполный", data.is_first_month_partial],
    ["Последний месяц неполный", data.is_last_month_partial],
    ["Объект", data.location || "Все"], ["Категория", data.category || "Все"],
    ["Страховой запас, дней", data.service_days],
    ["Лимит, ₽", data.budget_limit],
  ]);

  const positions = section("Новые позиции плана", target);
  positions.append(table(
    ["Товар / категория", "Объект", "Поставщик", "Заказ", "Приход", "Покрытие",
      "Потребность", "Количество", "Цена, ₽", "Стоимость, ₽", "Источник цены"],
    data.items.map((item) => [
      `${item.sku} / ${item.category}`, item.location, item.supplier,
      item.order_date, item.delivery_date,
      `${value(item.coverage_start)} — ${value(item.coverage_end)}`,
      item.raw_quantity, item.quantity, item.unit_price, item.total_cost, item.price_source,
    ]),
  ));
  data.items.forEach((item, index) => {
    details(positions, `${item.sku} · позиция ${index + 1}: показатели и предупреждения`,
      { metrics: item.metrics, warnings: item.warnings, is_undated: item.is_undated });
  });

  const orders = section("Уже оформленные заказы", target);
  orders.append(table(
    ["Документ", "Товар", "Объект", "Ожидается", "В пути", "Цена, ₽", "Поставщик"],
    data.existing_orders.map((order) => [order.doc_number, order.sku, order.location,
      order.expected_date, order.pending_qty, order.unit_price, order.supplier_name || order.supplier_id]),
  ));

  const budget = data.budget;
  const summary = section("Бюджет новых позиций", target);
  pairs(summary, [
    [budget.is_price_complete ? "Общий бюджет, ₽" : "Известная часть бюджета, ₽", budget.known_total],
    ["Цена полная", budget.is_price_complete],
    ["Позиции без цены", budget.unknown_price_count],
    ["Даты полные", budget.is_dates_complete],
    ["Недатированные позиции", budget.undated_count],
    ["Общее количество", budget.total_quantity],
    ["Лимит, ₽", budget.budget_limit],
    ["Статус лимита", budget.limit_status],
    ["Разница с лимитом, ₽", budget.limit_difference],
  ]);
  renderBreakdown(target, "По месяцам", budget.by_month,
    (item) => `${item.month}${item.is_partial ? " (неполный месяц)" : ""}`);
  renderBreakdown(target, "По товарам", budget.by_sku, (item) => item.sku);
  renderBreakdown(target, "По категориям", budget.by_category, (item) => item.category);
  renderBreakdown(target, "По объектам", budget.by_location, (item) => item.location);
  renderBreakdown(target, "Без даты заказа", [budget.undated], () => "Недатированные");
  details(target, "Предупреждения плана", data.warnings);
  explanation(target, data.explanation);
}

