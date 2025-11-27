import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { renderWithProviders } from "../test/utils";
import { vi, beforeEach, describe, it, expect } from "vitest";
import { apiClient } from "../api/client";

const mockFetchWorkers = vi.fn();

vi.mock("../hooks/useDomains", () => ({
  useDomains: () => [
    { domain: "prod", label: "prod" },
    { domain: "staging", label: "staging" },
  ],
}));

vi.mock("../hooks/useEvents", () => ({
  useSchedulerEvents: () => [],
}));

vi.mock("../components/EventsFeed", () => ({
  EventsFeed: () => <div>EventsFeed</div>,
}));

vi.mock("../api/jobs", () => ({
  fetchWorkers: (...args: unknown[]) => mockFetchWorkers(...args),
  fetchJobs: vi.fn().mockResolvedValue([]),
  fetchHistory: vi.fn().mockResolvedValue([]),
  fetchJobOverview: vi.fn().mockResolvedValue([]),
  fetchQueueOverview: vi.fn().mockResolvedValue({ pending: [], upcoming: [] }),
  fetchJobRuns: vi.fn().mockResolvedValue([]),
  fetchJob: vi.fn().mockResolvedValue(null),
  fetchJobGrid: vi.fn().mockResolvedValue({ rows: [] }),
  fetchJobGantt: vi.fn().mockResolvedValue({ rows: [] }),
  fetchJobGraph: vi.fn().mockResolvedValue({ nodes: [], links: [] }),
  createJob: vi.fn(),
  updateJob: vi.fn(),
  validateJob: vi.fn(),
  runJobNow: vi.fn(),
  runAdhocJob: vi.fn(),
}));

vi.mock("../api/admin", () => ({
  fetchDomains: vi.fn().mockResolvedValue({ domains: [] }),
  fetchTemplates: vi.fn().mockResolvedValue({ templates: [] }),
  rotateDomainToken: vi.fn(),
  createDomain: vi.fn(),
  updateDomain: vi.fn(),
  deleteDomain: vi.fn(),
  importTemplate: vi.fn(),
}));

describe("App navigation and routing", () => {
  const worker = {
    worker_id: "worker-123",
    status: "online",
    state: "online",
    domain: "prod",
    hostname: "host",
    ip: "127.0.0.1",
    os: "linux",
    deployment_type: "docker",
    subnet: "10.0.0.0/24",
    python_version: "3.11",
    run_user: "root",
    current_running: 1,
    max_concurrency: 4,
    queues: ["default"],
    tags: ["gpu"],
    allowed_users: ["alice"],
    running_jobs: ["job-a"],
    last_heartbeat: Date.now(),
  };
  const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue({});

  beforeEach(() => {
    mockFetchWorkers.mockResolvedValue([worker]);
    postSpy.mockClear();
  });

  it("renders IA groups and active domain tag", () => {
    renderWithProviders(<App />);
    expect(screen.getByText("Operate")).toBeInTheDocument();
    expect(screen.getByText("Observe")).toBeInTheDocument();
    expect(screen.getByText(/Domain: prod/i)).toBeInTheDocument();
  });

  it("routes to worker detail and allows state changes", async () => {
    renderWithProviders(<App />, { route: "/workers/worker-123" });
    expect(await screen.findByText("worker-123")).toBeInTheDocument();
    expect(screen.getByText("Running jobs")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Drain/i }));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith("/workers/worker-123/state", { state: "draining" }),
    );
  });
});
