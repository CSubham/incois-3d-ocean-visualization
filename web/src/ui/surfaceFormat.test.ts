import { describe, expect, it } from "vitest";

import { displayUnits, flowBearing, formatPosition } from "./surfaceFormat";

describe("surface formatting", () => {
  it("reads CF unit spellings", () => {
    expect(displayUnits("degree_Celsius")).toBe("°C");
    expect(displayUnits("m/s")).toBe("m/s");
    expect(displayUnits("1e-3")).toBe("1e-3");
  });

  it("gives the bearing the water flows toward", () => {
    expect(flowBearing(0, 1)).toEqual({ degrees: 0, compass: "N" });
    expect(flowBearing(1, 0).compass).toBe("E");
    expect(flowBearing(-1, -1).compass).toBe("SW");
  });

  it("formats hemispheres", () => {
    expect(formatPosition(85.5, -3.25)).toBe("3.25°S 85.50°E");
  });
});
