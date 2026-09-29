import { getJson, getAllPages } from "./api.js";
import { selectStock } from "./state.js";

const labels = {
  receipt: "Приход", consume: "Расход", writeoff: "Списание",
  return: "Возврат", correction: "Корректировка",
};
const $ = (selector) => document.querySelector(selector);
const value = (number, digits = 3) => number == null ? "Нет данных" : Number(number).toFixed(digits);
const date = (text) => text || "Нет данных";

function cell(row, content) {
  const td = document.createElement("td");
  td.textContent = String(content);
  row.append(td);
  return td;
}

function setStatus(element, message, kind = "loading") {
  element.className = `status ${kind}`;
  element.textContent = message;
}

function showRetry(button, visible) {
  button.hidden = !visible;
}

export function initWarehouse(state) {
  const stockStatus = $("#stock-status");
  const stockBody = $("#stock-body");
  const stockRetry = $("#stock-retry");
  const detailStatus = $("#detail-status");
  const detailBody = $("#batch-body");
  const detailRetry = $("#detail-retry");
  const journalStatus = $("#journal-status");
  const journalBody = $("#journal-body");
  const journalRetry = $("#journal-retry");
  const filterForm = $("#journal-filters");

  function renderStock(items) {
    stockBody.replaceChildren();
    for (const item of items) {
      const row = document.createElement("tr");
      if (item.sku === state.sku && item.location === state.location) row.className = "selected";
      const select = document.createElement("button");
      select.type = "button";
      select.className = "text-button";
      select.textContent = `${item.sku} · ${item.name}`;
      select.addEventListener("click", () => {
        selectStock(item.sku, item.location);
        renderStock(state.stockItems);
        loadDetail();
      });
      const firstCell = document.createElement("td");
      firstCell.append(select);
      row.append(firstCell);
      [item.location, value(item.current_stock), value(item.available_stock),
        value(item.expired_stock), value(item.average_daily_consumption, 6),
        value(item.days_of_stock), date(item.nearest_expiry_date)]
        .forEach((entry) => cell(row, entry));
      stockBody.append(row);
    }
    setStatus(stockStatus, `${items.length} из ${items.length} пар товаров и объектов`, "success");
  }

  async function loadStock() {
    const request = ++state.stockRequest;
    setStatus(stockStatus, "Загружаем остатки…");
    showRetry(stockRetry, false);
    try {
      const items = await getAllPages("/api/stock", { as_of: state.asOf });
      if (request !== state.stockRequest) return;
      state.stockItems = items;
      renderStock(items);
      if (!items.some((item) => item.sku === state.sku && item.location === state.location) && items.length) {
        selectStock(items[0].sku, items[0].location);
        renderStock(items);
      }
      await loadDetail();
    } catch (error) {
      if (request !== state.stockRequest) return;
      stockBody.replaceChildren();
      setStatus(stockStatus, `Ошибка загрузки остатков: ${error.message}`, "error");
      showRetry(stockRetry, true);
    }
  }

  async function loadDetail() {
    const request = ++state.detailRequest;
    const { sku, location, asOf } = state;
    $("#detail-title").textContent = `${sku} · ${location}`;
    setStatus(detailStatus, "Загружаем партии…");
    showRetry(detailRetry, false);
    detailBody.replaceChildren();
    try {
      const detail = await getJson(`/api/stock/${encodeURIComponent(sku)}`,
        { location, as_of: asOf });
      if (request !== state.detailRequest) return;
      const selected = detail.locations.find((item) => item.location === location);
      if (!selected) throw new Error("Для выбранного объекта нет данных.");
      $("#detail-balance").textContent =
        `Учётный: ${value(selected.current_stock)} · Доступный: ${value(selected.available_stock)} · Просроченный: ${value(selected.expired_stock)}`;
      for (const batch of selected.batches) {
        const row = document.createElement("tr");
        const expired = batch.expiry_date && batch.expiry_date < asOf;
        [batch.batch_id, batch.batch_number, date(batch.receipt_date),
          date(batch.expiry_date), value(batch.quantity), value(batch.available_quantity),
          value(batch.unit_price, 2), batch.receipt_doc_number,
          expired ? "Просрочена" : "Доступна"].forEach((entry) => cell(row, entry));
        if (expired) row.className = "expired";
        detailBody.append(row);
      }
      setStatus(detailStatus,
        selected.batches.length ? `${selected.batches.length} партий` : "Партии с остатком не найдены.", "success");
    } catch (error) {
      if (request !== state.detailRequest) return;
      $("#detail-balance").textContent = "";
      setStatus(detailStatus, `Ошибка загрузки партий: ${error.message}`, "error");
      showRetry(detailRetry, true);
    }
  }

  function renderAllocations(movement, target) {
    for (const allocation of movement.allocations) {
      const line = document.createElement("div");
      line.textContent = `Партия #${allocation.batch_id}: ${value(allocation.quantity)} по ${value(allocation.unit_price, 2)} ₽ · распределение #${allocation.id}`;
      target.append(line);
    }
    for (const warning of movement.warnings) {
      const line = document.createElement("div");
      line.className = "warning";
      line.textContent = `FEFO: ${warning.message}`;
      target.append(line);
    }
  }

  function renderJournal(page) {
    journalBody.replaceChildren();
    state.journal.total = page.total;
    for (const movement of page.items) {
      const row = document.createElement("tr");
      [movement.operation_date, movement.doc_number, movement.sku,
        movement.location, labels[movement.type] || movement.type,
        value(movement.quantity)].forEach((entry) => cell(row, entry));
      const info = document.createElement("td");
      if (movement.allocations.length || movement.warnings.length) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = `Распределения: ${movement.allocations.length}; предупреждения: ${movement.warnings.length}`;
        details.append(summary);
        renderAllocations(movement, details);
        info.append(details);
      } else {
        info.textContent = "—";
      }
      row.append(info);
      journalBody.append(row);
    }
    const from = page.total ? page.offset + 1 : 0;
    const to = page.offset + page.items.length;
    $("#journal-count").textContent = `Показано ${from}–${to} из ${page.total}`;
    $("#journal-prev").disabled = page.offset === 0;
    $("#journal-next").disabled = to >= page.total;
    setStatus(journalStatus, page.items.length ? "Журнал загружен." : "Записей по фильтрам нет.", "success");
  }

  async function loadJournal() {
    const request = ++state.journalRequest;
    const { filters, offset, limit } = state.journal;
    setStatus(journalStatus, "Загружаем журнал…");
    $("#journal-prev").disabled = true;
    $("#journal-next").disabled = true;
    showRetry(journalRetry, false);
    try {
      const page = await getJson("/api/movements", { ...filters, limit, offset });
      if (request !== state.journalRequest) return;
      renderJournal(page);
    } catch (error) {
      if (request !== state.journalRequest) return;
      journalBody.replaceChildren();
      setStatus(journalStatus, `Ошибка загрузки журнала: ${error.message}`, "error");
      showRetry(journalRetry, true);
    }
  }

  filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    state.journal.filters = Object.fromEntries(new FormData(filterForm));
    state.journal.offset = 0;
    loadJournal();
  });
  $("#journal-prev").addEventListener("click", () => {
    state.journal.offset = Math.max(0, state.journal.offset - state.journal.limit);
    loadJournal();
  });
  $("#journal-next").addEventListener("click", () => {
    state.journal.offset += state.journal.limit;
    loadJournal();
  });
  stockRetry.addEventListener("click", loadStock);
  detailRetry.addEventListener("click", loadDetail);
  journalRetry.addEventListener("click", loadJournal);

  return {
    async load() {
      filterForm.elements.date_to.value = state.asOf;
      state.journal.filters = Object.fromEntries(new FormData(filterForm));
      await Promise.all([loadStock(), loadJournal()]);
    },
    refresh: () => Promise.all([loadStock(), loadJournal()]),
  };
}
