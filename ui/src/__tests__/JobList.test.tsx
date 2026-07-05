import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect } from "vitest";
import { JobList } from "../components/JobList";
import { renderWithProviders } from "../test/utils";
import { JobDefinition } from "../types";

function makeJob(overrides: Partial<JobDefinition>): JobDefinition {
  return {
    _id: "job-1",
    name: "etl-nightly",
    user: "data-eng",
    domain: "prod",
    priority: 5,
    affinity: { os: [], tags: [], allowed_users: [] },
    executor: { type: "shell", script: "echo hi" },
    retries: 0,
    timeout: 30,
    schedule: { mode: "cron", cron: "0 2 * * *", enabled: true },
    completion: {
      exit_codes: [0],
      stdout_contains: [],
      stdout_not_contains: [],
      stderr_contains: [],
      stderr_not_contains: [],
    },
    tags: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  } as JobDefinition;
}

const jobs = [
  makeJob({ _id: "job-1", name: "etl-nightly", tags: ["batch"] }),
  makeJob({ _id: "job-2", name: "billing-reconcile", user: "finance", tags: ["finance"] }),
];

describe("JobList", () => {
  it("filters jobs by search text", async () => {
    renderWithProviders(<JobList jobs={jobs} onSelect={vi.fn()} />);
    expect(screen.getByText("etl-nightly")).toBeInTheDocument();
    expect(screen.getByText("billing-reconcile")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText(/Search name/i), "billing");

    expect(screen.queryByText("etl-nightly")).not.toBeInTheDocument();
    expect(screen.getByText("billing-reconcile")).toBeInTheDocument();
    expect(screen.getByText(/Showing 1 of 2 jobs/i)).toBeInTheDocument();
  });

  it("calls onToggleEnabled when the enabled switch is clicked", async () => {
    const onToggleEnabled = vi.fn();
    renderWithProviders(
      <JobList jobs={[jobs[0]]} onSelect={vi.fn()} onToggleEnabled={onToggleEnabled} />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(onToggleEnabled).toHaveBeenCalledWith(expect.objectContaining({ _id: "job-1" }), false),
    );
  });

  it("calls onDelete only after confirmation", async () => {
    const onDelete = vi.fn();
    renderWithProviders(<JobList jobs={[jobs[0]]} onSelect={vi.fn()} onDelete={onDelete} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /delete/i }));
    expect(onDelete).not.toHaveBeenCalled();

    await user.click(await screen.findByRole("button", { name: /^Delete$/ }));
    await waitFor(() =>
      expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ _id: "job-1" })),
    );
  });
});
