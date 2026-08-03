// Prefer a runtime-injected base URL (set by ui/docker-entrypoint.sh from
// HYDRA_API_BASE_URL at container start) over the Vite build-time constant,
// so one built image can be deployed against different scheduler endpoints
// without a rebuild — needed for the Helm chart's "build once" story.
const runtimeApiBase = (window as Window & { __HYDRA_API_BASE__?: string }).__HYDRA_API_BASE__;
const API_BASE = (runtimeApiBase && runtimeApiBase.trim()) || import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

type TokenMap = Record<string, string>;

const TOKEN_MAP_KEY = "hydra_token_map";
const ACTIVE_DOMAIN_KEY = "hydra_domain";
const TOKEN_PREFERENCE_KEY = "hydra_token_preference";
export const AUTH_REQUIRED_EVENT = "hydra-auth-required";

function readTokenMap(): TokenMap {
  try {
    const raw = localStorage.getItem(TOKEN_MAP_KEY);
    return raw ? (JSON.parse(raw) as TokenMap) : {};
  } catch {
    return {};
  }
}

function writeTokenMap(map: TokenMap) {
  localStorage.setItem(TOKEN_MAP_KEY, JSON.stringify(map));
}

export function setTokenForDomain(domain: string, token: string) {
  const map = readTokenMap();
  map[domain] = token;
  writeTokenMap(map);
}

export function setTokenPreference(preference: "domain" | "admin") {
  localStorage.setItem(TOKEN_PREFERENCE_KEY, preference);
}

export function getTokenForDomain(domain: string): string | undefined {
  return readTokenMap()[domain];
}

export function hasTokenForDomain(domain: string): boolean {
  return Boolean(getTokenForDomain(domain));
}

export function getAdminToken(): string | undefined {
  return readTokenMap()["admin"];
}

export function hasAnyToken(): boolean {
  const map = readTokenMap();
  return Object.keys(map).length > 0;
}

export function hasAuthContext(domain?: string): boolean {
  return getTokenContext(domain).source !== "none";
}

export function forgetToken(domain?: string) {
  if (!domain) {
    localStorage.removeItem(TOKEN_MAP_KEY);
    localStorage.removeItem(TOKEN_PREFERENCE_KEY);
    window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
    return;
  }
  const map = readTokenMap();
  delete map[domain];
  writeTokenMap(map);
  if (domain === "admin" && localStorage.getItem(TOKEN_PREFERENCE_KEY) === "admin") {
    localStorage.setItem(TOKEN_PREFERENCE_KEY, "domain");
  }
  if (Object.keys(map).length === 0) {
    window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
  }
}

export function setActiveDomain(domain: string) {
  localStorage.setItem(ACTIVE_DOMAIN_KEY, domain);
}

export function getActiveDomain(): string {
  return localStorage.getItem(ACTIVE_DOMAIN_KEY) || "prod";
}

type TokenContext =
  | { token: string; activeDomain: string; source: "domain" | "admin" }
  | { token?: undefined; activeDomain: string; source: "none" };

export function getTokenContext(domain?: string): TokenContext {
  const map = readTokenMap();
  const activeDomain = domain || getActiveDomain();
  const tokenPreference = localStorage.getItem(TOKEN_PREFERENCE_KEY);
  if (tokenPreference === "admin" && map["admin"]) {
    return { token: map["admin"], activeDomain, source: "admin" };
  }
  if (map[activeDomain]) {
    return { token: map[activeDomain], activeDomain, source: "domain" };
  }
  if (map["admin"]) {
    return { token: map["admin"], activeDomain, source: "admin" };
  }
  return { activeDomain, source: "none" };
}

export function getEffectiveToken(domain?: string): string | undefined {
  return getTokenContext(domain).token;
}

export function withTempToken<T>(token: string | undefined, fn: () => Promise<T>): Promise<T> {
  const currentDomain = getActiveDomain();
  const map = readTokenMap();
  const prev = map[currentDomain];
  if (token) {
    map[currentDomain] = token;
    writeTokenMap(map);
  }
  return fn().finally(() => {
    if (prev) {
      setTokenForDomain(currentDomain, prev);
    }
  });
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
    }
    const detail = await res.json().catch(() => ({} as any));
    const rawDetail = detail?.detail;
    if (Array.isArray(rawDetail)) {
      const flat = rawDetail
        .map((item: any) => {
          if (typeof item === "string") return item;
          if (item?.msg) return String(item.msg);
          return JSON.stringify(item);
        })
        .join("; ");
      throw new Error(flat || res.statusText);
    }
    if (rawDetail && typeof rawDetail === "object") {
      throw new Error(JSON.stringify(rawDetail));
    }
    throw new Error(rawDetail ?? res.statusText);
  }
  return res.json();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  const { token, activeDomain, source } = getTokenContext();
  if (token) {
    headers.set("x-api-key", token);
  }
  const url = new URL(path, API_BASE);
  if (!url.searchParams.has("domain")) {
    url.searchParams.set("domain", activeDomain);
  }
  const res = await fetch(url.toString(), { ...init, headers });
  return handleResponse<T>(res);
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  delete: <T>(path: string) =>
    request<T>(path, {
      method: "DELETE",
    }),
};

async function requestWithExplicitToken(path: string, token: string, domain?: string): Promise<Response> {
  const headers = new Headers();
  headers.set("x-api-key", token);
  const url = new URL(path, API_BASE);
  if (domain && !url.searchParams.has("domain")) {
    url.searchParams.set("domain", domain);
  }
  return fetch(url.toString(), { headers });
}

export async function validateDomainToken(domain: string, token: string): Promise<void> {
  const res = await requestWithExplicitToken("/jobs/", token, domain);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? "Invalid domain token");
  }
}

export async function validateAdminToken(token: string): Promise<void> {
  const res = await requestWithExplicitToken("/admin/domains", token);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? "Invalid admin token");
  }
}

export const streamUrl = () => {
  const { token, activeDomain } = getTokenContext();
  const url = new URL("/events/stream", API_BASE);
  if (token) {
    url.searchParams.set("token", token);
  }
  if (!url.searchParams.has("domain")) {
    url.searchParams.set("domain", activeDomain);
  }
  return url.toString();
};
export const runStreamUrl = (runId: string) => {
  const { token, activeDomain } = getTokenContext();
  const url = new URL(`/runs/${runId}/stream`, API_BASE);
  if (token) {
    url.searchParams.set("token", token);
  }
  if (!url.searchParams.has("domain")) {
    url.searchParams.set("domain", activeDomain);
  }
  return url.toString();
};
