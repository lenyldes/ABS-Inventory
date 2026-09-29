/** HTTP-клиент сайта: относительные пути сохраняют единый адрес веб-прокси. */
export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

/** Сохраняет фактический обмен, включая JSON тела ошибочного HTTP-ответа. */
export async function exchangeJson(method, path, { params = {}, body = null, signal } = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }
  const request = { method, url: url.pathname + url.search, body: method === "GET" ? null : body };
  try {
    const response = await fetch(url, {
      method, signal,
      headers: { Accept: "application/json", ...(body === null ? {} : { "Content-Type": "application/json" }) },
      ...(body === null ? {} : { body: JSON.stringify(body) }),
    });
    try {
      return { request, response: { status: response.status, body: await response.json() }, error: null };
    } catch {
      return { request, response: { status: response.status, body: null },
        error: { kind: "invalid_json", message: "Сервер вернул невалидный JSON." } };
    }
  } catch (error) {
    if (error.name === "AbortError") throw error;
    return { request, response: { status: null, body: null },
      error: { kind: "network", message: "Не удалось связаться с сервером." } };
  }
}

export async function getJson(path, params = {}, { signal } = {}) {
  return unwrap(await exchangeJson("GET", path, { params, signal }));
}

function unwrap({ response, error }) {
  if (error?.kind === "network") {
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение и повторите запрос.");
  }
  if (error || response.body === null) {
    throw new ApiError("Сервер вернул ответ без данных.", response.status);
  }
  const body = response.body;
  if (response.status < 200 || response.status >= 300) {
    const detail = body?.detail;
    const baseMessage = body?.message || detail?.message ||
      (typeof detail === "string" ? detail : `Ошибка сервера (${response.status})`);
    const details = body?.details || detail?.details || null;
    const errors = details?.errors;
    const message = Array.isArray(errors) && errors.length
      ? `${baseMessage}: ${errors.map((item) => item.message || item.msg || String(item)).join("; ")}`
      : baseMessage;
    throw new ApiError(message, response.status, details);
  }
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
  return unwrap(await exchangeJson("POST", path, { body: payload, signal }));
}
