import { describe, expect, it } from "vitest";

import { fromScene, sceneFrame, suggestedExaggeration, toScene, TransformError } from "./transform";

const bounds = { west: 80, east: 92, south: 5, north: 21 };

describe("scene transform", () => {
  it("round-trips positions exactly enough to report them back", () => {
    const frame = sceneFrame("EPSG:4326", "m", "down", bounds);
    const [lon, lat, depth] = fromScene(frame, ...toScene(frame, 84.4, 12.3, 750));
    expect(lon).toBeCloseTo(84.4, 9);
    expect(lat).toBeCloseTo(12.3, 9);
    expect(depth).toBeCloseTo(750, 6);
  });

  it("puts deeper water lower for positive-down and flips for positive-up", () => {
    const down = sceneFrame("EPSG:4326", "m", "down", bounds);
    const up = sceneFrame("EPSG:4326", "m", "up", bounds);
    expect(toScene(down, 86, 13, 1000)[1]).toBeCloseTo(-1);
    expect(toScene(up, 86, 13, -1000)[1]).toBeCloseTo(-1);
  });

  it("refuses a reference or unit it does not understand", () => {
    expect(() => sceneFrame("EPSG:3857", "m", "down", bounds)).toThrow(TransformError);
    expect(() => sceneFrame("EPSG:4326", "fathoms", "down", bounds)).toThrow(TransformError);
    expect(() => sceneFrame("EPSG:4326", null, "down", bounds)).toThrow(TransformError);
  });

  it("suggests a round exaggeration that makes depth readable", () => {
    expect(suggestedExaggeration(1300, 1)).toBe(300);
    expect(suggestedExaggeration(100, 0)).toBe(1);
  });
});
