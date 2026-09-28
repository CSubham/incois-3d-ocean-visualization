import { describe, expect, it } from "vitest";

import { logScaleProblem, normalise, paletteColour, ScaleError } from "./colour";

describe("colour mapping", () => {
  it("maps range ends to palette ends and clamps outside", () => {
    expect(paletteColour("viridis", 0)).toEqual(paletteColour("viridis", -3));
    expect(paletteColour("viridis", 1)).toEqual(paletteColour("viridis", 7));
    expect(paletteColour("viridis", 0).map((c) => Math.round(c * 255))).toEqual([0x44, 0x01, 0x54]);
  });

  it("normalises linearly and logarithmically", () => {
    expect(normalise(15, 10, 20, "linear")).toBeCloseTo(0.5);
    expect(normalise(10, 1, 100, "log")).toBeCloseTo(0.5);
    expect(normalise(5, 5, 5, "linear")).toBe(0.5);
  });

  it("refuses a log scale over a range that is not positive", () => {
    expect(logScaleProblem(0, 10)).toMatch(/above zero/);
    expect(logScaleProblem(1, 10)).toBeNull();
    expect(() => normalise(1, -1, 10, "log")).toThrow(ScaleError);
  });
});
