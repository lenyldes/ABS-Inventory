/** Сценарии записи используют сегодняшнюю дату Москвы и новый документ на каждый запуск. */
export function todayMoscow() {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Europe/Moscow", year: "numeric",
    month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function nextDay(date) {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}

function identity() {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 16).toUpperCase();
}

function base(type, quantity, date, doc) {
  return { operation_date: date, sku: "OIL-001", location: "MS-01", type,
    quantity, doc_number: doc };
}

function movement(body, expected, label) {
  return { method: "POST", path: "/api/movements", body, expected, label };
}

function balanceLines(body) {
  return [`ID движения: ${body.id}`, `Документ: ${body.doc_number}`,
    `Учётный остаток: ${body.current_stock}`, `Доступный остаток: ${body.available_stock}`];
}

export function writeCases() {
  const receipt = {
    id: "receipt", title: "Приход", goal: "Создать партию и показать новый остаток.",
    prepare() {
      const date = todayMoscow();
      const id = identity();
      const body = { ...base("receipt", "2.000", date, `CHECK-R-${id}`),
        batch_number: `CHECK-B-${id}`, expiry_date: nextDay(date), unit_price: "100.00" };
      return [movement(body, 201, "Провести приход"),
        { method: "GET", path: "/api/stock/OIL-001", params: { location: "MS-01", as_of: date },
          expected: 200, label: "Проверить новую партию" }];
    },
    async run(send, [step, detailStep]) {
      const { body } = step;
      const created = await send(step);
      if (!created) return;
      await send({ ...detailStep, summarize(result) {
          const row = result?.locations?.find((item) => item.location === detailStep.params.location);
          const batch = row?.batches?.find((item) => item.batch_number === body.batch_number);
          return row && batch ? [`Партия #${batch.batch_id}: ${batch.batch_number}, срок ${batch.expiry_date}`,
            `Учётный остаток: ${row.current_stock}`, `Доступный остаток: ${row.available_stock}`] : null;
        } });
    },
  };
  const consume = {
    id: "consume", title: "Расход FEFO", goal: "Провести расход и объяснить выбор партий.",
    prepare() {
      const date = todayMoscow();
      const id = identity();
      const receiptBody = { ...base("receipt", "2.000", date, `CHECK-R-${id}`),
        batch_number: `CHECK-B-${id}`, expiry_date: nextDay(date), unit_price: "100.00" };
      return [movement(receiptBody, 201, "Подготовить партию"),
        movement(base("consume", "1.000", date, `CHECK-C-${id}`), 201, "Провести расход"),
        { method: "GET", path: "/api/stock/OIL-001", params: { location: "MS-01", as_of: date },
          expected: 200, label: "Связать FEFO с партиями" }];
    },
    async run(send, [receiptStep, consumeStep, detailStep]) {
      if (!await send(receiptStep)) return;
      const result = await send({ ...consumeStep, summarize(response) {
        const amount = response?.allocations?.reduce((sum, item) => sum + Number(item.quantity), 0);
        return amount === Number(consumeStep.body.quantity) ? [...balanceLines(response),
          ...response.allocations.map((item) => `Партия #${item.batch_id}: ${item.quantity}`)] : null;
      } });
      if (!result) return;
      await send({ ...detailStep, summarize(detail) {
          const batches = detail?.locations?.find((item) => item.location === detailStep.params.location)?.batches || [];
          return result.allocations?.map((allocation) => {
            const batch = batches.find((item) => item.batch_id === allocation.batch_id);
            return `Партия #${allocation.batch_id}: ${allocation.quantity}, срок ${batch?.expiry_date || "Нет данных"}`;
          }) || null;
        } });
    },
  };
  const failures = [
    ["unknown_sku", "Неизвестный SKU", (body) => ({ ...body, sku: "CHECK-UNKNOWN-SKU" }), 404],
    ["unknown_location", "Неизвестный объект", (body) => ({ ...body, location: "CHECK-UNKNOWN-LOCATION" }), 404],
    ["zero_consume", "Нулевой расход", (body) => ({ ...body, quantity: "0" }), 422],
    ["zero_receipt", "Нулевой приход", (body) => ({ ...body, type: "receipt", quantity: "0",
      batch_number: `CHECK-B-${identity()}`, unit_price: "100.00" }), 422],
    ["overconsume", "Избыточный расход", (body) => ({ ...body, quantity: "1000000.000" }), 422],
    ["future", "Будущая дата", (body) => ({ ...body, operation_date: nextDay(body.operation_date) }), 422],
  ].map(([id, title, alter, expected]) => ({
    id, title, goal: "Проверить отказ API без нового движения.",
    prepare() {
      const body = alter(base("consume", "1.000", todayMoscow(), `CHECK-${identity()}`));
      return [movement(body, expected, title)];
    },
    async run(send, [step]) {
      await send(step);
    },
  }));
  const duplicate = {
    id: "duplicate", title: "Повтор документа", goal: "Показать успешный первый запрос и отказ 409 на его точной копии.",
    prepare() {
      const body = base("consume", "1.000", todayMoscow(), `CHECK-D-${identity()}`);
      return [movement(body, 201, "Первое движение"),
        movement({ ...body }, 409, "Повторить тот же запрос")];
    },
    async run(send, [step, repeated]) {
      if (!await send(step)) return;
      await send(repeated);
    },
  };
  return [receipt, consume, ...failures, duplicate];
}
