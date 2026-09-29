/** Редактор подготовленного HTTP-запроса без изменения списка проверяемых маршрутов. */
const labels = {
  path: "Путь API",
  sku: "SKU", location: "Объект", as_of: "Дата снимка", date_to: "Дата по",
  limit: "Лимит", offset: "Смещение", type: "Тип", horizon_months: "Горизонт, мес.",
  operation_date: "Дата операции", quantity: "Количество", doc_number: "Номер документа",
  batch_number: "Номер партии", expiry_date: "Срок годности", unit_price: "Цена",
};

const movementTypes = [
  ["receipt", "Приход"], ["consume", "Расход"], ["writeoff", "Списание"],
  ["return", "Возврат"], ["correction", "Корректировка"],
];
const alertTypes = [
  ["stockout", "Дефицит"], ["potential_stockout", "Возможный дефицит"],
  ["expiring_soon", "Истекает срок"], ["expired", "Просрочено"],
  ["no_movement", "Нет движения"], ["writeoff_risk", "Риск списания"],
  ["incomplete_history", "Неполная история"],
];
const numericFields = {
  limit: [1, 1], offset: [0, 1], horizon_months: [1, 1],
  quantity: [null, "0.001"], unit_price: [0, "0.01"],
};
const dateFields = new Set(["as_of", "date_from", "date_to", "operation_date", "expiry_date"]);

function choices(key, step) {
  if (key === "type" && step.path.startsWith("/api/movements")) return movementTypes;
  if (key === "type" && step.path.startsWith("/api/alerts")) return alertTypes;
  if (key === "level" && step.path.startsWith("/api/alerts")) {
    return [["critical", "Критический"], ["warning", "Предупреждение"], ["info", "Информация"]];
  }
  if (key === "sort_by" && step.path.startsWith("/api/movements")) {
    return [["operation_date", "Дата операции"], ["created_at", "Дата создания"]];
  }
  if (key === "sort_order" && step.path.startsWith("/api/movements")) {
    return [["asc", "По возрастанию"], ["desc", "По убыванию"]];
  }
  return null;
}

function inputField(key, value, step) {
  const label = document.createElement("label");
  label.textContent = labels[key] || key;
  const options = choices(key, step);
  const input = document.createElement(options ? "select" : "input");
  if (options) {
    if (step.method === "GET") input.append(new Option("Все", ""));
    for (const [code, title] of options) input.append(new Option(`${title} (${code})`, code));
  } else if (dateFields.has(key)) {
    input.type = "date";
  } else if (numericFields[key]) {
    input.type = "number";
    const [min, increment] = numericFields[key];
    if (min !== null) input.min = String(min);
    input.step = String(increment);
  }
  input.name = key;
  input.value = value ?? "";
  input.autocomplete = "off";
  label.append(input);
  return { label, input };
}

export function requestEditor(step) {
  const box = document.createElement("div");
  box.className = "verification-request";
  const heading = document.createElement("strong");
  heading.textContent = `${step.label || "Запрос"} (${step.path})`;
  const address = document.createElement("code");
  const fields = document.createElement("div");
  fields.className = "verification-fields";
  const path = inputField("path", step.path, step);
  fields.append(path.label);
  const source = step.method === "GET" ? step.params || {} : step.body || {};
  const controls = Object.entries(source).map(([key, value]) => [key, value, inputField(key, value, step)]);
  for (const [, , control] of controls) fields.append(control.label);

  function read() {
    const values = Object.fromEntries(controls.map(([key, original, { input }]) => [
      key, typeof original === "number" && input.value !== "" ? Number(input.value) : input.value,
    ]));
    return { ...step, path: path.input.value,
      ...(step.method === "GET" ? { params: values } : { body: values }) };
  }

  function updateAddress() {
    const current = read();
    try {
      const url = new URL(current.path, window.location.origin);
      for (const [key, value] of Object.entries(current.params || {})) {
        if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
      }
      address.textContent = `${current.method} ${url.pathname}${url.search}`;
    } catch {
      address.textContent = "Некорректный путь запроса";
    }
  }
  fields.addEventListener("input", updateAddress);
  fields.addEventListener("change", updateAddress);
  box.append(heading, address, fields);
  updateAddress();
  return { element: box, read, updateAddress };
}
