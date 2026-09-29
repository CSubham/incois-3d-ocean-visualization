import { describe, expect, it } from "vitest";

import { detailExtent } from "./detail";

// Catalogue extents are signed, whatever the stored axis convention.
const globe = { west: -179.92, east: 180, south: -80, north: 90 };
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

  it("sends a western-hemisphere view as signed longitudes", () => {
    const extent = detailExtent(globe, { west: -70, east: -60, south: 10, north: 20 }, 4)!;
    expect(extent.west).toBe(-71);
    expect(extent.east).toBe(-59);
  });

  it("sends a view across the antimeridian with east beyond 180", () => {
    const extent = detailExtent(globe, { west: 170, east: -170, south: 0, north: 10 }, 4)!;
    expect(extent.west).toBe(168);
    expect(extent.east).toBe(192);
  });
});
