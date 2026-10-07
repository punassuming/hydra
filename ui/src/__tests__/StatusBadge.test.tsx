import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StatusBadge, getStatusConfig } from "../components/StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["success", "Success"],
    ["running", "Running"],
    ["failed", "Failed"],
    ["error", "Error"],
    ["timed_out", "Timed out"],
    ["dispatched", "Dispatched"],
    ["pending", "Queued"],
    ["queued", "Queued"],
  ])("renders %s with text and an icon (not color alone)", (status, text) => {
    const config = getStatusConfig(status);
    expect(config.text).toBe(text);
    expect(config.icon).not.toBeNull();
  });

  it("gives timed_out a distinct label from failed", () => {
    expect(getStatusConfig("timed_out").text).not.toBe(getStatusConfig("failed").text);
  });

  it("falls back to an icon plus the raw status for unknown values", () => {
    const config = getStatusConfig("something_new");
    expect(config.text).toBe("something_new");
    expect(config.icon).not.toBeNull();
  });

  it("exposes an accessible label", () => {
    render(<StatusBadge status="timed_out" />);
    expect(screen.getByLabelText("Status: Timed out")).toBeTruthy();
  });
});
