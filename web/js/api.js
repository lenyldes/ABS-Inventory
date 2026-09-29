/** HTTP-клиент сайта: относительные пути сохраняют единый адрес веб-прокси. */
export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export async function getJson(path, params = {}, { signal } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  let response;
  try {
    response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение и повторите запрос.");
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const baseMessage = body?.message || detail?.message ||
      (typeof detail === "string" ? detail : `Ошибка сервера (${response.status})`);
    const details = body?.details || detail?.details || null;
    const errors = details?.errors;
    const message = Array.isArray(errors) && errors.length
      ? `${baseMessage}: ${errors.map((error) => error.message || error.msg || String(error)).join("; ")}`
      : baseMessage;
    throw new ApiError(message, response.status, details);
  }
  if (body === null) throw new ApiError("Сервер вернул ответ без данных.", response.status);
  return body;
}

export async function getAllPages(path, params = {}, { signal } = {}) {
  const items = [];
  const limit = 100;
  let offset = 0;
  do {
    const page = await getJson(path, { ...params, limit, offset }, { signal });
    items.push(...page.items);
    offset += page.items.length;
    if (!page.items.length || offset >= page.total) return items;
  } while (true);
}

export async function postJson(path, payload, { signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      signal,
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение и повторите запрос.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const message = body?.message || detail?.message ||
      (typeof detail === "string" ? detail : `Ошибка сервера (${response.status})`);
    const errors = body?.details?.errors || detail?.details?.errors;
    throw new ApiError(Array.isArray(errors) && errors.length
      ? `${message}: ${errors.map((error) => error.message || error.msg || String(error)).join("; ")}`
      : message, response.status, body?.details || detail?.details || null);
  }
  if (body === null) throw new ApiError("Сервер вернул ответ без данных.", response.status);
  return body;
}
