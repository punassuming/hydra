import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect } from "vitest";
import { JobForm } from "../components/JobForm";
import { renderWithProviders } from "../test/utils";

vi.mock("../api/jobs", () => ({
  fetchWorkers: vi.fn().mockResolvedValue([]),
}));

describe("JobForm stepper", () => {
  it("moves through steps and blocks submit when validation fails", async () => {
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
    // move to last step
    for (let i = 0; i < 4; i += 1) {
      await user.click(screen.getByRole("button", { name: /Next/i }));
    }
    expect(screen.getByText(/Completion/i)).toBeInTheDocument();

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
    for (let i = 0; i < 4; i += 1) {
      await user.click(screen.getByRole("button", { name: /Next/i }));
    }
    await user.click(screen.getByRole("button", { name: /Validate & Submit/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  });
});
