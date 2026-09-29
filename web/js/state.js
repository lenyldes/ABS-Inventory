/** Общее состояние страницы. Дата снимка задаётся только ответом API статуса. */
export const state = {
  asOf: null,
  sku: "DEMO-OIL",
  location: "DEMO-MS-01",
  locationFilter: "",
  category: "",
  horizonMonths: 3,
  serviceDays: 14,
  budgetLimit: "",
  stockItems: [],
  stockRequest: 0,
  detailRequest: 0,
  journalRequest: 0,
  journal: { filters: {}, offset: 0, limit: 10, total: 0 },
  forecastRequest: 0,
  planRequest: 0,
  alertsRequest: 0,
};

export function selectStock(sku, location) {
  state.sku = sku;
  state.location = location;
  document.dispatchEvent(new Event("stock-selection-changed"));
}
