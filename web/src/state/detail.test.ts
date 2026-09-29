import { describe, expect, it } from "vitest";

import { detailExtent } from "./detail";

const globe360 = { west: 0, east: 359.92, south: -80, north: 90 };
const indian = { west: 30, east: 120, south: -30, north: 30 };

describe("detail extent", () => {
  it("is not needed when the base layer already has source cells", () => {
    expect(detailExtent(indian, { west: 80, east: 90, south: 5, north: 15 }, 1)).toBeNull();
  });

  it("is not needed when most of the field is in view", () => {
    expect(detailExtent(indian, { west: 25, east: 125, south: -35, north: 35 }, 3)).toBeNull();
  });

  it("covers the view with a margin, snapped outward and clipped to the field", () => {
    expect(detailExtent(indian, { west: 80.2, east: 90.1, south: 5.3, north: 15.4 }, 3))
      .toEqual({ west: 79, east: 91.5, south: 4, north: 16.5 });
  });

  it("maps a western-hemisphere view onto a 0..360 field", () => {
    const extent = detailExtent(globe360, { west: -70, east: -60, south: 10, north: 20 }, 4)!;
    expect(extent.west).toBe(289);
    expect(extent.east).toBe(301);
  });

  it("leaves a view across the field's seam to the base layer", () => {
    expect(detailExtent(globe360, { west: -5, east: 5, south: 0, north: 10 }, 4)).toBeNull();
  });
});
