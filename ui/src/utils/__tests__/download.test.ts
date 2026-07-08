import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { downloadJson, slugify } from "../download";

describe("slugify", () => {
  it("lowercases and hyphenates", () => {
    expect(slugify("Nightly ETL Job!")).toBe("nightly-etl-job");
  });

  it("falls back to 'job' for empty input", () => {
    expect(slugify("   ")).toBe("job");
  });
});

describe("downloadJson", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    revokeObjectURL = vi.fn();
    (URL as unknown as { createObjectURL: typeof createObjectURL }).createObjectURL = createObjectURL;
    (URL as unknown as { revokeObjectURL: typeof revokeObjectURL }).revokeObjectURL = revokeObjectURL;
    clickSpy = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clickSpy);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates an object URL, triggers a click with the given filename, then revokes it", () => {
    downloadJson("hydra-jobs-export.json", { hello: "world" });

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blobArg = createObjectURL.mock.calls[0][0] as Blob;
    expect(blobArg.type).toBe("application/json");

    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });
});
