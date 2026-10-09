import "../antdReact19";
import { act, screen } from "@testing-library/react";
import { message } from "antd";
import entrySource from "../main.tsx?raw";
import { afterEach, describe, expect, it } from "vitest";

// The UI calls antd's *static* message API all over (AuthPrompt, HeaderSettings,
// Admin, Workers, ...). On React 19 those only render if the compatibility patch
// is loaded; a type-check and component tests would not notice them going silent.
describe("antd static message API on React 19", () => {
  afterEach(() => {
    message.destroy();
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
