import { describe, expect, it } from "vitest";

import { formatUtc } from "./format";

describe("formatUtc", () => {
  it("formats every UTC spelling the catalogue and product use", () => {
    expect(formatUtc("2024-09-05T09:00:00.000000000")).toBe("2024-09-05 09:00 UTC");
    expect(formatUtc("2024-09-05T09:00:00+00:00")).toBe("2024-09-05 09:00 UTC");
  });
  it("shows a non-zero offset as given rather than shifting it", () => {
    expect(formatUtc("2024-09-05T14:30:00+05:30")).toBe("2024-09-05 14:30 +05:30");
  });
});
