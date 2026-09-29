import { postJson } from "./api.js";

const $ = (selector) => document.querySelector(selector);
const moscowToday = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit",
}).format(new Date());
const fieldsByType = {
  receipt: ["batch_number", "expiry_date", "unit_price", "purchase_order_id", "supplier_id"],
  consume: [],
  writeoff: ["batch_id", "reason"],
  return: ["parent_movement_id", "parent_allocation_id", "reason"],
  correction: ["batch_id", "reason"],
};
const formMarkup = `
  <div class="section-heading">
    <div><p class="eyebrow">Операция</p><h2 id="movement-title">Провести движение</h2></div>
    <span id="movement-status" class="status success" role="status">Укажите параметры движения.</span>
  </div>
  <p class="hint">Можно проводить движения для любого SKU, включая DEMO-. После перезапуска приложения стенд вернётся к исходным данным. ID партий, движений и распределений можно взять из таблиц выше или ввести вручную.</p>
  <form id="movement-form" class="filters">
    <label>Дата операции <input name="operation_date" type="date" required></label>
    <label>SKU <input name="sku" value="OIL-001" maxlength="64" required></label>
    <label>Объект <input name="location" value="MS-01" maxlength="64" required></label>
    <label>Тип <select name="type">
      <option value="receipt">Приход</option><option value="consume">Расход</option>
      <option value="writeoff">Списание</option><option value="return">Возврат</option>
      <option value="correction">Корректировка</option>
    </select></label>
    <label>Количество <input name="quantity" type="number" step="0.001" value="2.000" required></label>
    <label>Номер документа <input name="doc_number" maxlength="64" required placeholder="Новый уникальный номер"></label>
    <label data-movement-field="batch_number">Номер партии <input name="batch_number" maxlength="128" required></label>
    <label data-movement-field="expiry_date">Срок годности <input name="expiry_date" type="date"></label>
    <label data-movement-field="unit_price">Цена за единицу, ₽ <input name="unit_price" type="number" min="0" step="0.01" required></label>
    <label data-movement-field="purchase_order_id">ID заказа <input name="purchase_order_id" type="number" min="1" step="1"></label>
    <label data-movement-field="supplier_id">Код поставщика <input name="supplier_id" maxlength="64"></label>
    <label data-movement-field="batch_id">ID партии <input name="batch_id" type="number" min="1" step="1" list="movement-batches"></label>
    <label data-movement-field="parent_movement_id">ID исходного расхода <input name="parent_movement_id" type="number" min="1" step="1" list="movement-parents"></label>
    <label data-movement-field="parent_allocation_id">ID распределения расхода <input name="parent_allocation_id" type="number" min="1" step="1" list="movement-allocations"></label>
    <label data-movement-field="reason">Причина <input name="reason"></label>
    <button id="movement-submit" type="submit">Провести движение</button>
  </form>
  <datalist id="movement-batches"></datalist>
  <datalist id="movement-parents"></datalist>
  <datalist id="movement-allocations"></datalist>
  <div id="movement-result" aria-live="polite"></div>
`;

function setStatus(element, message, kind) {
  element.className = `status ${kind}`;
  element.textContent = message;
}

function updateReferences(warehouse) {
  const { batches, movements } = warehouse.visibleReferences();
  const lists = {
    "movement-batches": batches.map((batch) => [batch.batch_id, batch.batch_number]),
    "movement-parents": movements.filter((item) => item.type === "consume")
      .map((item) => [item.id, item.doc_number]),
    "movement-allocations": movements.flatMap((item) => item.allocations
      .map((allocation) => [allocation.id, `Движение #${item.id}, партия #${allocation.batch_id}`])),
  };
  for (const [id, options] of Object.entries(lists)) {
    const list = $(`#${id}`);
    list.replaceChildren();
    for (const [value, label] of options) {
      const option = document.createElement("option");
      option.value = String(value);
      option.label = label;
      list.append(option);
    }
  }
}

function showResult(result) {
  const container = $("#movement-result");
  container.replaceChildren();
  const summary = document.createElement("p");
  summary.textContent = `Движение #${result.id}, документ ${result.doc_number}. ` +
    `Учётный остаток: ${result.current_stock}; доступный: ${result.available_stock}.`;
  container.append(summary);
  if (result.allocations.length) {
    const heading = document.createElement("p");
    heading.textContent = "Распределения по партиям:";
    const list = document.createElement("ul");
    for (const allocation of result.allocations) {
      const line = document.createElement("li");
      line.textContent = `#${allocation.id}: партия #${allocation.batch_id}, ` +
        `${allocation.quantity} по ${allocation.unit_price} ₽`;
      list.append(line);
    }
    container.append(heading, list);
  }
}

export function initMovementForm(warehouse) {
  $("#movement").innerHTML = formMarkup;
  let pending = false;
  const form = $("#movement-form");
  const status = $("#movement-status");
  const submit = $("#movement-submit");
  const type = form.elements.type;
  form.elements.operation_date.value = moscowToday();

  function updateType() {
    const active = fieldsByType[type.value];
    for (const field of form.querySelectorAll("[data-movement-field]")) {
      const enabled = active.includes(field.dataset.movementField);
      field.hidden = !enabled;
      field.style.display = enabled ? "" : "none";
      field.querySelector("input").disabled = !enabled;
    }
    for (const name of ["batch_number", "unit_price", "batch_id", "parent_movement_id",
      "parent_allocation_id", "reason"]) {
      form.elements[name].required = active.includes(name) &&
        !(name === "reason" && type.value === "return");
    }
    form.elements.quantity.min = type.value === "correction" ? "" : "0.001";
    updateReferences(warehouse);
  }

  type.addEventListener("change", updateType);
  form.addEventListener("focusin", () => updateReferences(warehouse));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending || !form.reportValidity()) return;
    const data = new FormData(form);
    const payload = {};
    for (const name of ["operation_date", "sku", "location", "type", "quantity", "doc_number",
      ...fieldsByType[type.value]]) {
      const value = String(data.get(name) || "").trim();
      if (!value) continue;
      payload[name] = ["batch_id", "parent_movement_id", "parent_allocation_id",
        "purchase_order_id"].includes(name) ? Number(value) : value;
    }
    pending = true;
    submit.disabled = true;
    $("#movement-result").replaceChildren();
    setStatus(status, "Проводим движение…", "loading");
    try {
      const result = await postJson("/api/movements", payload);
      showResult(result);
      setStatus(status, `Движение #${result.id} проведено (201).`, "success");
      await warehouse.refreshAfterMovement(moscowToday(), result.sku, result.location);
      updateReferences(warehouse);
    } catch (error) {
      const code = [400, 404, 409, 422].includes(error.status) ? `HTTP ${error.status}: ` : "";
      setStatus(status, `${code}${error.message}`, "error");
    } finally {
      pending = false;
      submit.disabled = false;
    }
  });
  updateType();
}
