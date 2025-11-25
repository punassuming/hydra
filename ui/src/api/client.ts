const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type TokenMap = Record<string, string>;

const TOKEN_MAP_KEY = "hydra_token_map";
const ACTIVE_DOMAIN_KEY = "hydra_domain";

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

export function getTokenForDomain(domain: string): string | undefined {
  return readTokenMap()[domain];
}

export function forgetToken(domain?: string) {
  if (!domain) {
    localStorage.removeItem(TOKEN_MAP_KEY);
    return;
  }
  const map = readTokenMap();
  delete map[domain];
  writeTokenMap(map);
}

export function setActiveDomain(domain: string) {
  localStorage.setItem(ACTIVE_DOMAIN_KEY, domain);
}

export function getActiveDomain(): string {
  return localStorage.getItem(ACTIVE_DOMAIN_KEY) || "prod";
}

export function getEffectiveToken(domain?: string): string | undefined {
  const map = readTokenMap();
  const active = domain || getActiveDomain();
  return map[active] || map["admin"];
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
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? res.statusText);
  }
  return res.json();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  const token = getEffectiveToken();
  if (token) {
    headers.set("x-api-key", token);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
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
};

export const streamUrl = () => {
  const token = getEffectiveToken();
  return token ? `${API_BASE}/events/stream?token=${encodeURIComponent(token)}` : `${API_BASE}/events/stream`;
};
export const runStreamUrl = (runId: string) => {
  const token = getEffectiveToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${API_BASE}/runs/${runId}/stream${qs}`;
};
