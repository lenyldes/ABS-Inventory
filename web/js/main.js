import { getJson } from "./api.js";
import { state } from "./state.js";
import { initWarehouse } from "./warehouse.js";
import { initAnalytics } from "./analytics.js";

const startup = document.querySelector("#startup-status");
const snapshot = document.querySelector("#snapshot-date");
const retry = document.querySelector("#retry-start");
const warehouse = initWarehouse(state);
const analytics = initAnalytics(state);

async function start() {
  retry.hidden = true;
  startup.className = "status loading";
  startup.textContent = "Загружаем дату демонстрационного снимка…";
  try {
    const status = await getJson("/api/demo/status");
    if (!status.ready || !status.as_of) throw new Error("Демонстрационный набор пока не готов.");
    state.asOf = status.as_of;
    snapshot.textContent = status.as_of;
    startup.className = "status success";
    startup.textContent = `Данные на ${status.as_of}`;
    await Promise.all([warehouse.load(), analytics.load()]);
  } catch (error) {
    startup.className = "status error";
    startup.textContent = `Не удалось открыть данные: ${error.message}`;
    retry.hidden = false;
  }
}

retry.addEventListener("click", start);
start();
