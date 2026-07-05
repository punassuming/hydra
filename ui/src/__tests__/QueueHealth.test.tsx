import { screen, waitFor } from "@testing-library/react";
import { vi, describe, it, expect } from "vitest";
import { QueueHealth } from "../components/QueueHealth";
import { renderWithProviders } from "../test/utils";

const mockFetchQueuePressure = vi.fn();

vi.mock("../api/jobs", () => ({
  fetchQueuePressure: () => mockFetchQueuePressure(),
}));

describe("QueueHealth", () => {
  it("shows a starvation warning when jobs are stalled", async () => {
    mockFetchQueuePressure.mockResolvedValue({
      domains: [
        {
          domain: "prod",
          pending_total: 4,
          stalled_jobs: ["job-a", "job-b"],
          stalled_count: 2,
          max_no_worker_count: 7,
          starvation_threshold: 5,
          worker_queue_depths: {},
          total_worker_queue_depth: 0,
          online_workers: 1,
          total_running: 1,
          total_capacity: 4,
        },
      ],
    });
    renderWithProviders(<QueueHealth />);
    await waitFor(() => expect(screen.getByText(/2 job\(s\) are starved for workers/i)).toBeInTheDocument());
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(screen.getByText("2 stalled")).toBeInTheDocument();
  });

  it("shows no warning when nothing is stalled", async () => {
    mockFetchQueuePressure.mockResolvedValue({
      domains: [
        {
          domain: "prod",
          pending_total: 0,
          stalled_jobs: [],
          stalled_count: 0,
          max_no_worker_count: 0,
          starvation_threshold: 5,
          worker_queue_depths: {},
          total_worker_queue_depth: 0,
          online_workers: 2,
          total_running: 0,
          total_capacity: 8,
        },
      ],
    });
    renderWithProviders(<QueueHealth />);
    await waitFor(() => expect(screen.getByText("prod")).toBeInTheDocument());
    expect(screen.queryByText(/starved for workers/i)).not.toBeInTheDocument();
    expect(screen.getByText("none")).toBeInTheDocument();
  });
});
