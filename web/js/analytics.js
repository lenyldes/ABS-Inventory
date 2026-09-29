import { getAllPages, postJson } from "./api.js";
import { details, element, explanation, pairs, renderPlan, section } from "./plan-view.js";

function renderAlerts(items) {
  const body = document.querySelector("#alerts-body");
  body.replaceChildren();
  if (!items.length) {
    const row = body.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 5;
    cell.textContent = "Предупреждений нет";
  }
  items.forEach((alert) => {
    const row = body.insertRow();
    [alert.type, alert.level, alert.sku, alert.location].forEach(
      (field) => row.append(element("td", field)),
    );
    const info = row.insertCell();
    info.append(element("p", alert.message));
    details(info, "Исходные показатели", alert.metrics);
  });
}

function renderForecast(data) {
  const target = document.querySelector("#forecast-result");
  target.replaceChildren();
  const block = section("Потребность и рекомендация", target);
  pairs(block, [
    ["Период", `${data.horizon_start} — ${data.horizon_end} (${data.days_count} дней)`],
    ["Учётный остаток", data.current_stock],
    ["Доступный остаток", data.available_stock],
    ["Средний расход за день", data.average_daily_consumption],
    ["Прогноз расхода", data.forecast_consumption],
    ["Поставки в пути", data.incoming_qty],
    ["Страховой запас", data.safety_stock],
    ["Точка заказа", data.reorder_point],
    ["Рекомендуемое количество", data.recommended_qty],
    ["Цена за единицу, ₽", data.unit_price],
    ["Стоимость, ₽", data.total_cost],
    ["Дата дефицита", data.stockout_date],
    ["Дата заказа", data.order_date],
    ["История полная", data.is_history_complete],
    ["Дней истории", data.history_days],
  ]);
  details(target, "Предупреждения прогноза", data.warnings);
  explanation(target, data.explanation, data.daily_forecast);
}

function status(id, message, kind) {
  const node = document.querySelector(`#${id}-status`);
  node.className = `status ${kind}`;
  node.textContent = message;
  document.querySelector(`#${id}-retry`).hidden = kind !== "error";
}

export function initAnalytics(state) {
  const form = document.querySelector("#plan-filters");

  async function alerts() {
    const request = ++state.alertsRequest;
    status("alerts", "Загружаем предупреждения…", "loading");
    document.querySelector("#alerts-body").replaceChildren();
    try {
      const items = await getAllPages("/api/alerts", { as_of: state.asOf });
      if (request !== state.alertsRequest) return;
      renderAlerts(items);
      status("alerts", `${items.length} предупреждений`, "success");
    } catch (error) {
      if (request === state.alertsRequest) status("alerts", error.message, "error");
    }
  }

  async function forecast() {
    const request = ++state.forecastRequest;
    const { sku, location, asOf } = state;
    document.querySelector("#forecast-pair").textContent = `${sku} · ${location}`;
    document.querySelector("#forecast-result").replaceChildren();
    status("forecast", "Рассчитываем прогноз…", "loading");
    try {
      const data = await postJson("/api/forecast", {
        sku, location, as_of: asOf,
        horizon_months: state.horizonMonths, service_days: state.serviceDays,
      });
      if (request !== state.forecastRequest) return;
      renderForecast(data);
      status("forecast", "Прогноз рассчитан", "success");
    } catch (error) {
      if (request === state.forecastRequest) status("forecast", error.message, "error");
    }
  }

  async function plan() {
    const request = ++state.planRequest;
    const fields = new FormData(form);
    const months = Number(fields.get("horizon_months"));
    const days = Number(fields.get("service_days"));
    if (!form.reportValidity() || ![1, 3, 6, 12].includes(months) ||
      !Number.isInteger(days) || days < 0) return;
    state.horizonMonths = months;
    state.serviceDays = days;
    state.locationFilter = String(fields.get("location") || "").trim();
    state.category = String(fields.get("category") || "").trim();
    state.budgetLimit = String(fields.get("budget_limit") || "").trim();
    const payload = {
      as_of: state.asOf, horizon_months: months, service_days: days,
      location: state.locationFilter || null, category: state.category || null,
      budget_limit: state.budgetLimit || null,
    };
    document.querySelector("#plan-result").replaceChildren();
    status("plan", "Рассчитываем план…", "loading");
    try {
      const data = await postJson("/api/procurement/plan", payload);
      if (request !== state.planRequest) return;
      renderPlan(data);
      status("plan", "План рассчитан", "success");
    } catch (error) {
      if (request === state.planRequest) status("plan", error.message, "error");
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    plan();
    forecast();
  });
  form.elements.horizon_months.addEventListener("change", () => {
    plan();
    forecast();
  });
  document.addEventListener("stock-selection-changed", () => {
    if (state.asOf) forecast();
  });
  document.querySelector("#alerts-retry").addEventListener("click", alerts);
  document.querySelector("#forecast-retry").addEventListener("click", forecast);
  document.querySelector("#plan-retry").addEventListener("click", plan);
  return { load: () => Promise.all([alerts(), forecast(), plan()]) };
}
