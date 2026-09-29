import { describe, expect, it } from "vitest";

import { cellAt, gridGeometry, rasterise, robustRange, SurfaceError } from "./surface";

const lon = new Float64Array([30, 30.08, 30.16]);
const lat = new Float64Array([-1, -0.96]);   // south to north

describe("surface grids", () => {
  it("places cell edges half a step outside the source coordinates", () => {
    const g = gridGeometry(lon, lat);
    expect(g.west).toBeCloseTo(29.96);
    expect(g.east).toBeCloseTo(30.2);
    expect(g.south).toBeCloseTo(-1.02);
    expect(g.north).toBeCloseTo(-0.94);
    expect(g.latitudeAscending).toBe(true);
  });

  it("accepts a regular axis stored with rounding, as HYCOM stores longitude", () => {
    const rounded = new Float64Array([30.0, 30.0799560546875, 30.1600341796875, 30.239990234375]);
    expect(gridGeometry(rounded, lat).longitudeStep).toBeCloseTo(0.08, 4);
  });

  it("refuses irregular spacing instead of stretching the image", () => {
    expect(() => gridGeometry(new Float64Array([0, 1, 3]), lat)).toThrow(SurfaceError);
  });

  it("draws the north row first and leaves missing cells transparent", () => {
    const g = gridGeometry(lon, lat);
    // Source row 0 is south: 0,1,2; row 1 is north: 3,4 and a missing cell.
    const values = new Float32Array([0, 1, 2, 3, 4, 5]);
    const mask = new Uint8Array([0, 0, 0, 0, 0, 1]);
    const pixels = rasterise(values, mask, g, { palette: "viridis", range: { minimum: 0, maximum: 4 }, scale: "linear" });
    // First pixel row is the north source row: value 3, opaque.
    expect(pixels[3]).toBe(255);
    // Its third pixel is the missing cell.
    expect(pixels[2 * 4 + 3]).toBe(0);
    // The top-left pixel (value 3) differs from the bottom-left one (value 0).
    expect(Array.from(pixels.slice(0, 3))).not.toEqual(Array.from(pixels.slice(12, 15)));
  });

  it("rotates a whole 0..360 globe to start at the antimeridian", () => {
    const globe = new Float64Array(36).map((_, i) => 5 + i * 10);   // 5..355
    const g = gridGeometry(globe, lat);
    expect(g.imageWest).toBe(-180);
    expect(g.imageEast).toBe(180);
    expect(globe[g.firstColumn]).toBe(185);   // west edge 180 = -180
    const values = new Float32Array(72).map((_, i) => i % 36);
    const pixels = rasterise(values, new Uint8Array(72), g, { palette: "viridis", range: { minimum: 0, maximum: 35 }, scale: "linear" });
    const reference = rasterise(new Float32Array(72).fill(18), new Uint8Array(72), g, { palette: "viridis", range: { minimum: 0, maximum: 35 }, scale: "linear" });
    // The first pixel shows source column 18 (lon 185).
    expect(Array.from(pixels.slice(0, 3))).toEqual(Array.from(reference.slice(0, 3)));
    // A pointer at -175 (= 185) finds that same source column.
    expect(cellAt(g, -175, -1)).toBe(18);
  });

  it("lets a regional field cross the antimeridian", () => {
    const g = gridGeometry(new Float64Array([170, 175, 180, 185, 190]), lat);
    expect(g.imageWest).toBeCloseTo(167.5);
    expect(g.imageEast).toBeCloseTo(-167.5);
    expect(g.firstColumn).toBe(0);
  });

  it("finds the source cell under a position, and nothing outside", () => {
    const g = gridGeometry(lon, lat);
    expect(cellAt(g, 30.09, -0.97)).toBe(1 * 3 + 1);
    expect(cellAt(g, 30.0, -1.0)).toBe(0);
    expect(cellAt(g, 50, 0)).toBeNull();
  });

  it("keeps a few extreme values from washing out the colour range", () => {
    const values = new Float32Array(1000).map((_, i) => 20 + (i % 10));
    values[0] = -50;   // one outlier
    const range = robustRange(values, new Uint8Array(1000))!;
    expect(range.minimum).toBeGreaterThan(-50);
    expect(range.maximum).toBeGreaterThanOrEqual(29);
  });
});
