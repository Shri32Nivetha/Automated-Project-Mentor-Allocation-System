const BASE = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
const TOKEN_KEY = "pga_token";

export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY));

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.fieldErrors = detail && detail.errors ? Object.fromEntries(detail.errors.map((e) => [e.field, e.message])) : {};
  }
}

function toMessage(detail, status) {
  if (!detail) return `Request failed (${status})`;
  if (typeof detail === "string") return detail;
  if (detail.message) return detail.message;
  return `Request failed (${status})`;
}

async function raw(path, { method = "GET", body, params } = {}) {
  const url = new URL(BASE + path);
  Object.entries(params || {}).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && url.searchParams.set(k, v));
  const headers = {};
  const t = getToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError("Cannot reach the server. Check that the backend is running and VITE_API_URL is correct.", 0);
  }
  if (res.status === 401 && t && !path.startsWith("/auth/login")) {
    setToken(null);
    window.dispatchEvent(new Event("pga-session-expired"));
  }
  if (!res.ok) {
    let detail = null;
    try { detail = (await res.json()).detail; } catch { /* non-JSON error body */ }
    throw new ApiError(toMessage(detail, res.status), res.status, detail);
  }
  return res;
}

export async function api(path, opts) {
  const res = await raw(path, opts);
  if (res.status === 204) return null;
  return res.json();
}

export async function download(path, filename, params) {
  const res = await raw(path, { params });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
export const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : "—");
