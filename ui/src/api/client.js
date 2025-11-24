const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
let cachedToken = localStorage.getItem("hydra_token") || "";
export function setAuthToken(token) {
    cachedToken = token;
    localStorage.setItem("hydra_token", token);
}
export function getToken() {
    return cachedToken || localStorage.getItem("hydra_token") || undefined;
}
export function setDomain(domain) {
    localStorage.setItem("hydra_domain", domain);
}
async function handleResponse(res) {
    if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail?.detail ?? res.statusText);
    }
    return res.json();
}
async function request(path, init) {
    const headers = new Headers(init?.headers || {});
    const token = getToken();
    if (token) {
        headers.set("x-api-key", token);
    }
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
    return handleResponse(res);
}
export const apiClient = {
    get: (path) => request(path),
    post: (path, body) => request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    }),
    put: (path, body) => request(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    }),
};
export const streamUrl = () => {
    const token = getToken();
    return token ? `${API_BASE}/events/stream?token=${encodeURIComponent(token)}` : `${API_BASE}/events/stream`;
};
export const runStreamUrl = (runId) => {
    const token = getToken();
    const qs = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${API_BASE}/runs/${runId}/stream${qs}`;
};
