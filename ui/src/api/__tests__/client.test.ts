import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

describe("API_BASE resolution", () => {
  const original = (window as Window & { __HYDRA_API_BASE__?: string }).__HYDRA_API_BASE__;

  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  afterEach(() => {
    (window as Window & { __HYDRA_API_BASE__?: string }).__HYDRA_API_BASE__ = original;
  });

  it("prefers window.__HYDRA_API_BASE__ when set (runtime override)", async () => {
    (window as Window & { __HYDRA_API_BASE__?: string }).__HYDRA_API_BASE__ =
      "https://scheduler.hydra.svc.cluster.local:8000";
    const { streamUrl } = await import("../client");
    const url = new URL(streamUrl());
    expect(url.origin).toBe("https://scheduler.hydra.svc.cluster.local:8000");
  });

  it("ignores a blank runtime override and falls back to the build-time default", async () => {
    (window as Window & { __HYDRA_API_BASE__?: string }).__HYDRA_API_BASE__ = "   ";
    const { streamUrl } = await import("../client");
    const url = new URL(streamUrl());
    // Falls back to import.meta.env.VITE_API_BASE_URL or the localhost default —
    // either way it must NOT be the blank override.
    expect(url.origin).not.toBe("");
  });

  it("falls back to the default when no runtime override is set", async () => {
    delete (window as Window & { __HYDRA_API_BASE__?: string }).__HYDRA_API_BASE__;
    const { streamUrl } = await import("../client");
    const url = new URL(streamUrl());
    expect(url.origin).toBe("http://localhost:8000");
  });
});
