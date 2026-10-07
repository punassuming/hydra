import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunInspector } from "../components/RunInspector";
import { renderWithProviders } from "../test/utils";
import type { JobRun } from "../types";

type Listener = (evt: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, Listener[]> = {};
  onmessage: Listener | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: Listener) {
    (this.listeners[type] ??= []).push(fn);
  }
  close() {}
  emit(type: string, data: string) {
    const evt = { data } as MessageEvent;
    (this.listeners[type] ?? []).forEach((fn) => fn(evt));
  }
}

const runningRun = {
  _id: "run-1",
  job_id: "job-1",
  status: "running",
  stdout: "",
  stderr: "",
} as unknown as JobRun;

describe("RunInspector live log streaming", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders chunks the server sends as named log_chunk events", async () => {
    renderWithProviders(<RunInspector run={runningRun} open onClose={() => {}} />);

    const source = FakeEventSource.instances[0];
    expect(source).toBeDefined();
    // Regression: the server emits `event: log_chunk`, which onmessage never
    // receives, so a dedicated listener must be registered.
    expect(source.listeners["log_chunk"]?.length).toBeGreaterThan(0);

    act(() => {
      source.emit("log_chunk", JSON.stringify({ text: "streamed-line-from-server\n", stream: "stdout" }));
    });

    expect((await screen.findAllByText(/streamed-line-from-server/)).length).toBeGreaterThan(0);
  });
});
