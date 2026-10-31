/**
 * Two ways to run the same app: against the Cardiotic server (real accounts, uploads, storage), or static
 * (recorded sample data, nothing leaves the browser). The server is detected when the app starts: if
 * `/api/health` answers, the app is in server mode.
 */
export let serverMode = false;
/** The hospital's name, public so the sign-in page can show it before anyone has signed in. */
export let siteName: string | undefined;

export async function detectMode(): Promise<boolean> {
  try {
    const res = await fetch(`${import.meta.env.BASE_URL.replace(/\/$/, "")}/api/health`, { signal: AbortSignal.timeout(2000), credentials: "same-origin" });
    const body = res.ok && (res.headers.get("content-type") ?? "").includes("json") ? await res.json() : null;
    serverMode = body?.status === "ok";
    siteName = body?.site_name;
  } catch {
    serverMode = false;
  }
  return serverMode;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const API = () => `${import.meta.env.BASE_URL.replace(/\/$/, "")}/api`;

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const res = await fetch(`${API()}${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(method !== "GET" ? { "X-Requested-With": "cardiotic" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const type = res.headers.get("content-type") ?? "";
  const body = type.includes("json") ? await res.json() : await res.arrayBuffer();
  if (!res.ok) {
    const message = (body as { error?: string }).error ?? `HTTP ${res.status}`;
    if (res.status === 401 && path !== "/login") window.dispatchEvent(new CustomEvent("cardiotic:signed-out"));
    throw new ApiError(res.status, message);
  }
  return body as T;
}
