import "../antdReact19";
import { act, screen } from "@testing-library/react";
import { message } from "antd";
import entrySource from "../main.tsx?raw";
import { afterEach, describe, expect, it } from "vitest";

// The UI calls antd's *static* message API all over (AuthPrompt, HeaderSettings,
// Admin, Workers, ...). On React 19 those only render if the compatibility patch
// is loaded; a type-check and component tests would not notice them going silent.
describe("antd static message API on React 19", () => {
  // The static API renders into its own React root, and its leave animation never
  // finishes in jsdom, so the DOM is not a usable "done" signal. Unmount inside
  // act() and let the queued React work and motion timers run while jsdom still
  // exists; otherwise they fire after vitest tears it down and fail the whole run
  // with an unhandled "window is not defined" (intermittent under parallel load).
  afterEach(async () => {
    await act(async () => {
      message.destroy();
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
  });

  it("renders message.success / message.error into the document", async () => {
    act(() => {
      message.success("Token saved for domain prod");
      message.error("Domain token required");
    });
    expect(await screen.findByText("Token saved for domain prod")).toBeInTheDocument();
    expect(await screen.findByText("Domain token required")).toBeInTheDocument();
  });

  it("is loaded before anything else by the real entry point", () => {
    const firstImport = entrySource.split("\n").find((line) => line.startsWith("import "));
    expect(firstImport).toBe('import "./antdReact19";');
  });
});
