import { exchangeJson } from "./api.js";
import { readCases } from "./verification-read.js";
import { requestEditor } from "./verification-request.js";
import { writeCases } from "./verification-write.js";

const $ = (selector) => document.querySelector(selector);

function allowedPath(path) {
  try {
    const url = new URL(path, window.location.origin);
    return path.startsWith("/api/") && url.origin === window.location.origin &&
      url.pathname.startsWith("/api/");
  } catch {
    return false;
  }
}

function node(tag, value, className) {
  const element = document.createElement(tag);
  if (value != null) element.textContent = value;
  if (className) element.className = className;
  return element;
}

function jsonDetails(label, data) {
  const details = node("details");
  details.append(node("summary", label), node("pre", JSON.stringify(data, null, 2)));
  return details;
}

function stepRow(step, editable = true) {
  const grid = node("div", null, "verification-chain");
  const request = node("div", null, "verification-stage");
  const editor = editable ? requestEditor(step) : null;
  if (editor) request.append(editor.element);
  else request.append(node("strong", step.label || "Запрос"), node("code", `${step.method} ${step.path}`),
    jsonDetails("Тело запроса", step.body ?? "без тела"));
  const sent = node("div", null, "verification-sent");
  sent.hidden = true;
  request.append(sent);
  const response = node("div", null, "verification-stage");
  const result = node("div", null, "verification-stage");
  response.hidden = true;
  result.hidden = true;
  grid.append(request, response, result);
  return { element: grid, response, result, sent,
    read: editor?.read || (() => step), update: editor?.updateAddress };
}

function defaultSummary(step, body) {
  if (step.expected === 201) {
    return body?.id > 0 && body.doc_number === step.body.doc_number
      ? [`ID движения: ${body.id}`, `Документ: ${body.doc_number}`,
        `Учётный остаток: ${body.current_stock}`, `Доступный остаток: ${body.available_stock}`] : null;
  }
  if (step.expected >= 400) {
    const message = body?.message || body?.detail?.message || body?.detail;
    const code = body?.code || body?.detail?.code;
    return message ? [`Сообщение: ${message}`, `Код: ${code || "Нет данных"}`,
      ...(body?.details?.available == null ? [] : [`Доступно: ${body.details.available}`])] : null;
  }
  return body ? [] : null;
}

function showResult(row, step, exchange, lines, valid) {
  const { response, result } = row;
  row.sent.replaceChildren(node("small", `Отправлено: ${exchange.request.method} ${exchange.request.url}`),
    jsonDetails("Отправленное тело", exchange.request.body ?? "без тела"));
  row.sent.hidden = false;
  response.replaceChildren(node("strong", "Ответ"), node("p", exchange.response.status == null
    ? "Ответ не получен" : `HTTP ${exchange.response.status}`));
  if (exchange.error) response.append(node("p", exchange.error.message, "status error"));
  response.append(jsonDetails("Полный JSON ответа", exchange.response.body));
  result.replaceChildren(node("strong", "Результат"), node("p", valid
    ? step.expected === 201 ? "Движение проведено." : step.expected >= 400
      ? "Ожидаемый отказ: движение не проведено." : "Данные получены и сопоставлены."
    : "Расхождение с ожидаемым ответом.", `status ${valid ? "success" : "error"}`));
  for (const line of lines || []) result.append(node("p", line));
  response.hidden = false;
  result.hidden = false;
}

export function initVerification(asOf, warehouse) {
  const root = $("#verification-cases");
  root.replaceChildren();
  $("#verification-date").textContent = asOf;
  for (const item of [...readCases(asOf), ...writeCases()]) {
    const card = node("details", null, "verification-card");
    card.id = `check-${item.id}`;
    const summary = node("summary");
    const summaryTitle = node("span", item.title);
    const summaryPath = node("code");
    const summaryStatus = node("small", "Не запускалась");
    summary.append(summaryTitle, summaryPath, summaryStatus);
    card.append(summary, node("p", item.goal, "hint"));
    const requests = node("div", null, "verification-steps");
    card.append(requests);
    if (item.followUp) card.append(node("p", item.followUp, "hint"));
    const button = node("button", "Запустить проверку");
    button.type = "button";
    const status = node("span", "Ожидает запуска", "status");
    status.setAttribute("role", "status");
    card.append(button, status);
    let rows = [];
    let next = null;
    let renew = null;

    function prepare() {
      const steps = item.prepare ? item.prepare() : item.id === "journal"
        ? [...item.steps(0), ...item.steps(2)] : item.steps();
      summaryPath.textContent = `(${steps[0].path})`;
      summaryStatus.textContent = "Не запускалась";
      requests.replaceChildren();
      rows = steps.map((step) => stepRow(step));
      for (const row of rows) requests.append(row.element);
      if (item.id === "duplicate") {
        const first = rows[0].element.querySelectorAll("input, select");
        const repeated = rows[1].element.querySelectorAll("input, select");
        const sync = () => {
          first.forEach((input, index) => { repeated[index].value = input.value; });
          rows[1].update();
        };
        repeated.forEach((input) => { input.dataset.locked = "true"; input.disabled = true; });
        rows[0].element.addEventListener("input", sync);
        rows[0].element.addEventListener("change", sync);
        sync();
      }
      button.disabled = false;
      status.className = "status";
      status.textContent = "Ожидает запуска";
      if (renew) renew.hidden = true;
      if (next) next.disabled = true;
    }

    async function execute(indices) {
      const prepared = indices.map((index) => rows[index].read());
      if (prepared.some((step) => !allowedPath(step.path))) {
        status.className = "status error";
        status.textContent = "Путь запроса должен начинаться с /api/.";
        summaryStatus.textContent = "Ошибка пути";
        return;
      }
      button.disabled = true;
      if (next) next.disabled = true;
      status.className = "status loading";
      status.textContent = "Выполняется…";
      summaryStatus.textContent = "Выполняется…";
      for (const row of rows) {
        row.response.hidden = true;
        row.result.hidden = true;
        row.sent.hidden = true;
      }
      requests.querySelectorAll("input, select").forEach((input) => { input.disabled = true; });
      requests.querySelectorAll(".verification-chain[data-dynamic]").forEach((element) => element.remove());
      let allValid = true;
      let refreshIssue = false;
      let index = 0;

      async function send(step) {
        const preparedIndex = indices[index++];
        const row = preparedIndex == null ? stepRow(step, false) : rows[preparedIndex];
        if (preparedIndex == null) {
          row.element.dataset.dynamic = "true";
          requests.append(row.element);
        }
        const exchange = await exchangeJson(step.method, step.path,
          { params: step.params, body: step.body });
        const lines = !exchange.error && exchange.response.status === step.expected
          ? (step.summarize ? step.summarize(exchange.response.body) : defaultSummary(step, exchange.response.body)) : null;
        const valid = !exchange.error && exchange.response.status === step.expected && lines !== null;
        showResult(row, step, exchange, lines, valid);
        if (!valid) allValid = false;
        if (valid && step.expected === 201) {
          await warehouse.refreshAfterMovement(step.body.operation_date, step.body.sku, step.body.location)
            .catch(() => { refreshIssue = true; });
        }
        return valid ? exchange.response.body : null;
      }

      try {
        if (item.run) await item.run(send, prepared);
        else for (const step of prepared) await send(step);
        status.className = `status ${allValid ? "success" : "error"}`;
        status.textContent = allValid ? refreshIssue
          ? "Проверка выполнена, но склад не обновился." : "Проверка выполнена" : "Есть расхождение";
        summaryStatus.textContent = allValid ? "Выполнена" : "Расхождение";
      } catch (error) {
        status.className = "status error";
        status.textContent = `Проверка прервана: ${error.message}`;
        summaryStatus.textContent = "Ошибка";
      } finally {
        requests.querySelectorAll("input, select").forEach((input) => {
          input.disabled = input.dataset.locked === "true";
        });
        button.disabled = Boolean(item.prepare);
        if (renew) renew.hidden = false;
        if (next) next.disabled = !status.classList.contains("success") || indices[0] !== 0;
      }
    }

    button.addEventListener("click", () => execute(item.id === "journal" ? [0] : rows.map((_, index) => index)));
    if (item.id === "journal") {
      next = node("button", "Следующая страница");
      next.type = "button";
      next.disabled = true;
      next.addEventListener("click", () => execute([1]));
      card.append(next);
    }
    if (item.prepare) {
      renew = node("button", "Подготовить новый запрос");
      renew.type = "button";
      renew.hidden = true;
      renew.addEventListener("click", prepare);
      card.append(renew);
    }
    prepare();
    root.append(card);
  }
}
