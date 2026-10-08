import { describe, expect, it } from "vitest";
import { parseParams, PARAM_KEY_MAX_LENGTH } from "../params";

describe("parseParams", () => {
  it("parses KEY=VALUE lines and trims whitespace", () => {
    expect(parseParams("A=1\n  B = two words \n\nC=").params).toEqual({ A: "1", B: "two words", C: "" });
  });

  it("splits only on the first equals sign", () => {
    expect(parseParams("URL=https://x/y?a=b").params).toEqual({ URL: "https://x/y?a=b" });
  });

  it("accepts underscores, lowercase and digits after the first character", () => {
    const { params, errors } = parseParams("_x=1\nlower_case2=2");
    expect(errors).toEqual([]);
    expect(params).toEqual({ _x: "1", lower_case2: "2" });
  });

  it.each([["1BAD=x"], ["has-dash=x"], ["has space=x"], ["A;B=x"]])("reports %s as an invalid name", (line) => {
    const { params, errors } = parseParams(line);
    expect(params).toEqual({});
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/Line 1/);
  });

  it("reports a missing equals sign and an empty name with line numbers", () => {
    const { errors } = parseParams("OK=1\nNOEQUALS\n=value");
    expect(errors).toEqual([
      "Line 2: expected KEY=VALUE",
      "Line 3: parameter name is empty",
    ]);
  });

  it("rejects names longer than the maximum", () => {
    const { errors } = parseParams(`${"A".repeat(PARAM_KEY_MAX_LENGTH + 1)}=x`);
    expect(errors).toHaveLength(1);
  });

  it("keeps valid lines even when others are invalid", () => {
    const { params, errors } = parseParams("GOOD=1\n1BAD=2");
    expect(params).toEqual({ GOOD: "1" });
    expect(errors).toHaveLength(1);
  });
});
