import { describe, expect, it } from "vitest";

import type { CatalogueVersion, RequestView } from "../api/client";
import type { ProductDescriptor } from "../api/wire";
import { initialState, intentFor, reducer, type State } from "./store";

const version: CatalogueVersion = {
  id: "v1", dataset: "GLBy0.08", geometry: "grid",
  variables: [{ name: "water_temp", units: "degC" }], depth_levels: 33, time_steps: 1,
  extent: { time_start: "2024-09-05T09:00:00+00:00", time_end: "2024-09-05T09:00:00+00:00",
    depth_min: 0, depth_max: 1000, west: 80, east: 92, south: 5, north: 21 },
  created_at: "2026-09-29T00:00:00+00:00",
};

function succeeded(minimum: number, maximum: number): RequestView {
  return {
    request_id: "r1", state: "succeeded", finished: true, failure: null,
    budget: { requested_points: 200000, effective_points: 200000, reduced_by_server: false, maximum_cells: 5e6 },
    product: { product: { full_subset_range: { minimum, maximum, valid_point_count: 1, missing_point_count: 0 } } } as unknown as ProductDescriptor,
    links: { self: "/s", data: "/d" },
  };
}

const loaded = (): State => reducer(initialState(500_000), { type: "catalogueLoaded", versions: [version] });

describe("S7 state", () => {
  it("selects the first version with its full extent and a bounded budget", () => {
    const s = loaded();
    expect(s.selection).toMatchObject({ versionId: "v1", variable: "water_temp", west: 80, depthMaximum: 1000, maximumPoints: 200000 });
    expect(intentFor(s.selection!).time).toBe("2024-09-05T09:00:00+00:00");
  });

  it("never asks for more points than the renderer declares", () => {
    const s = reducer(loaded(), { type: "editSelection", patch: { maximumPoints: 9e9 } });
    expect(s.selection!.maximumPoints).toBe(500_000);
  });

  it("uses the full-subset range and a readable exaggeration for a new product", () => {
    const s = reducer(loaded(), { type: "requestFinished", view: succeeded(2.9, 31.7) });
    expect(s.display.range).toEqual({ minimum: 2.9, maximum: 31.7 });
    expect(s.display.rangeSource).toBe("full-subset");
    expect(s.display.verticalExaggeration).toBe(400);
  });

  it("keeps a custom range and exaggeration across products until reset", () => {
    let s = reducer(loaded(), { type: "setDisplay", patch: { range: { minimum: 10, maximum: 20 }, verticalExaggeration: 50 } });
    s = reducer(s, { type: "requestFinished", view: succeeded(2.9, 31.7) });
    expect(s.display.range).toEqual({ minimum: 10, maximum: 20 });
    expect(s.display.verticalExaggeration).toBe(50);
    s = reducer(s, { type: "useFullSubsetRange" });
    expect(s.display).toMatchObject({ range: { minimum: 2.9, maximum: 31.7 }, rangeSource: "full-subset" });
  });

  it("falls back to a linear scale when the new range cannot be logarithmic", () => {
    let s = reducer(loaded(), { type: "setDisplay", patch: { scale: "log" } });
    s = reducer(s, { type: "requestFinished", view: succeeded(-1.5, 30) });
    expect(s.display.scale).toBe("linear");
  });

  it("lowers the budget on a resource event and records the retry", () => {
    let s = reducer(loaded(), { type: "rendererEvent", event: { type: "resource", reason: "too many", retryWithPoints: 50_000 } });
    expect(s.selection!.maximumPoints).toBe(50_000);
    s = reducer(s, { type: "requestStarted", retryFrom: 200_000 });
    expect(s.lowerDensityRetry).toEqual({ from: 200_000, to: 50_000 });
  });

  it("tracks the sample under the pointer and clears it on a new field", () => {
    const sample = { longitude: 85, latitude: 12, depth: 50, value: 28.4 };
    let s = reducer(loaded(), { type: "rendererEvent", event: { type: "hover", sample } });
    expect(s.hovered).toEqual(sample);
    s = reducer(s, { type: "rendererEvent", event: { type: "ready", shownPoints: 10, hiddenMissingPoints: 2 } });
    expect(s.hovered).toBeNull();
  });

  it("leaves the field's budget alone when a marker is picked", () => {
    const before = loaded();
    const pick = { datasetVersionId: "v", platformId: "p", cycle: "1", longitude: 0, latitude: 0, observedAt: "t" };
    const after = reducer(before, { type: "rendererEvent", event: { type: "pick", marker: pick } });
    expect(after.selection).toEqual(before.selection);
  });

  it("reports a failed request and an unsupported renderer", () => {
    const failed: RequestView = { ...succeeded(0, 1), state: "failed", product: null, failure: { code: "work_limit", message: "too big" } };
    expect(reducer(loaded(), { type: "requestFinished", view: failed }).request)
      .toEqual({ phase: "failed", failure: { code: "work_limit", message: "too big" } });
    expect(reducer(loaded(), { type: "rendererEvent", event: { type: "unsupported", reason: "no WebGL2" } }).renderer)
      .toEqual({ phase: "unsupported", reason: "no WebGL2" });
  });
});
