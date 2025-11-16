const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.detail ?? res.statusText);
  }
  return res.json();
}

export const apiClient = {
  get: <T>(path: string) => handleResponse<T>(fetch(`${API_BASE}${path}`)),
  post: <T>(path: string, body: unknown) =>
    handleResponse<T>(
      fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
  put: <T>(path: string, body: unknown) =>
    handleResponse<T>(
      fetch(`${API_BASE}${path}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
};

export const streamUrl = `${API_BASE}/events/stream`;
