import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect } from "vitest";
import { JobForm } from "../components/JobForm";
import { renderWithProviders } from "../test/utils";

vi.mock("../api/jobs", () => ({
  fetchWorkers: vi.fn().mockResolvedValue([]),
  fetchJobs: vi.fn().mockResolvedValue([]),
  generateJob: vi.fn(),
}));

describe("JobForm", () => {
  it("blocks submit when validation fails", async () => {
    const onValidate = vi.fn().mockResolvedValue({ valid: false, errors: ["missing"] });
    const onSubmit = vi.fn();
    renderWithProviders(
      <JobForm
        onSubmit={onSubmit}
        onValidate={onValidate}
        onManualRun={vi.fn()}
        onAdhocRun={vi.fn()}
        submitting={false}
        validating={false}
        onReset={vi.fn()}
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Validate & Submit/i }));
    await waitFor(() => expect(onValidate).toHaveBeenCalled());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits when validation succeeds", async () => {
    const onValidate = vi.fn().mockResolvedValue({ valid: true, errors: [] });
    const onSubmit = vi.fn();
    renderWithProviders(
      <JobForm
        onSubmit={onSubmit}
        onValidate={onValidate}
        onManualRun={vi.fn()}
        onAdhocRun={vi.fn()}
        submitting={false}
        validating={false}
        onReset={vi.fn()}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Validate & Submit/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  });
});
