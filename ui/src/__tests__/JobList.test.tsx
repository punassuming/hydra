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

  it("shows a bulk action bar after selecting rows and invokes bulk handlers", async () => {
    const onBulkPause = vi.fn();
    const onBulkDelete = vi.fn();
    renderWithProviders(
      <JobList
        jobs={jobs}
        onSelect={vi.fn()}
        onBulkPause={onBulkPause}
        onBulkResume={vi.fn()}
        onBulkDelete={onBulkDelete}
      />,
    );
    const user = userEvent.setup();

    // Select all via header checkbox
    const checkboxes = screen.getAllByRole("checkbox");
    await user.click(checkboxes[0]);

    expect(await screen.findByText(/2 selected/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Pause/ }));
    expect(onBulkPause).toHaveBeenCalledWith(expect.arrayContaining([
      expect.objectContaining({ _id: "job-1" }),
      expect.objectContaining({ _id: "job-2" }),
    ]));

    // Selection clears after an action
    expect(screen.queryByText(/selected/i)).not.toBeInTheDocument();
  });

  it("does not render selection controls without bulk handlers", () => {
    renderWithProviders(<JobList jobs={jobs} onSelect={vi.fn()} />);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("exports the currently filtered jobs as sanitized JSON", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURL = vi.fn();
    (URL as unknown as { createObjectURL: typeof createObjectURL }).createObjectURL = createObjectURL;
    (URL as unknown as { revokeObjectURL: typeof revokeObjectURL }).revokeObjectURL = revokeObjectURL;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderWithProviders(<JobList jobs={jobs} onSelect={vi.fn()} />);
    const user = userEvent.setup();

    // Narrow to a single job first so only the filtered subset is exported.
    await user.type(screen.getByPlaceholderText(/Search name/i), "billing");
    await user.click(screen.getByRole("button", { name: /Export All/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    const text = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
    const exported = JSON.parse(text);

    expect(exported).toHaveLength(1);
    expect(exported[0].name).toBe("billing-reconcile");
    // Server-assigned fields must not be present in the export.
    expect(exported[0]._id).toBeUndefined();
    expect(exported[0].created_at).toBeUndefined();
    expect(exported[0].updated_at).toBeUndefined();

    vi.restoreAllMocks();
  });
});
