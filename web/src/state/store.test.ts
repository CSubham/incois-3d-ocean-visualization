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

function succeeded(minimum: number, maximum: number, depthUnits: string | null = "m"): RequestView {
  return {
    request_id: "r1", state: "succeeded", finished: true, failure: null,
    budget: { requested_points: 200000, effective_points: 200000, reduced_by_server: false, maximum_cells: 5e6 },
    product: {
      product: {
        full_subset_range: { minimum, maximum, valid_point_count: 1, missing_point_count: 0 },
        coordinates: { units: { depth: depthUnits }, dtypes: {}, time_encoding: {} },
      },
    } as unknown as ProductDescriptor,
    links: { self: "/s", data: "/d" },
  };
}

const loaded = (): State => reducer(initialState(500_000), { type: "catalogueLoaded", versions: [version] });
const shown = (state: State, view: RequestView, points = 10, hidden = 2): State =>
  reducer(state, { type: "productShown", view, shownPoints: points, hiddenMissingPoints: hidden });

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

  it("commits a product only when the renderer has shown it", () => {
    const s = shown(loaded(), succeeded(2.9, 31.7), 165_511, 34_489);
    expect(s.product).not.toBeNull();
    expect(s.request).toEqual({ phase: "shown" });
    expect(s.shown).toEqual({ points: 165_511, hiddenMissing: 34_489 });
    expect(s.display.range).toEqual({ minimum: 2.9, maximum: 31.7 });
    expect(s.display.rangeSource).toBe("full-subset");
  });

  it("keeps the previous product as the shown one when the renderer refuses a new one", () => {
    const before = shown(loaded(), succeeded(2.9, 31.7));
    const after = reducer(before, { type: "productRefused", reason: "CRS EPSG:3857 is not supported" });
    expect(after.product).toBe(before.product);
    expect(after.display).toEqual(before.display);
    expect(after.request).toEqual({ phase: "failed", failure: { code: "unsupported_product", message: "CRS EPSG:3857 is not supported" } });
  });

  it("suggests exaggeration from the product's own depth units", () => {
    expect(shown(loaded(), succeeded(0, 1, "m")).display.verticalExaggeration).toBe(400);
    // The same selected span in kilometres is a thousand times deeper.
    const km = reducer(loaded(), { type: "editSelection", patch: { depthMinimum: 0, depthMaximum: 1 } });
    expect(shown(km, succeeded(0, 1, "km")).display.verticalExaggeration).toBe(400);
  });

  it("does not guess an exaggeration when the depth units are unknown", () => {
    const before = loaded();
    expect(shown(before, succeeded(0, 1, "fathoms")).display.verticalExaggeration)
      .toBe(before.display.verticalExaggeration);
  });

  it("keeps a custom range and exaggeration across products until reset", () => {
    let s = reducer(loaded(), { type: "setDisplay", patch: { range: { minimum: 10, maximum: 20 }, verticalExaggeration: 50 } });
    s = shown(s, succeeded(2.9, 31.7));
    expect(s.display.range).toEqual({ minimum: 10, maximum: 20 });
    expect(s.display.verticalExaggeration).toBe(50);
    s = reducer(s, { type: "useFullSubsetRange" });
    expect(s.display).toMatchObject({ range: { minimum: 2.9, maximum: 31.7 }, rangeSource: "full-subset" });
  });

  it("falls back to a linear scale when the new range cannot be logarithmic", () => {
    let s = reducer(loaded(), { type: "setDisplay", patch: { scale: "log" } });
    s = shown(s, succeeded(-1.5, 30));
    expect(s.display.scale).toBe("linear");
  });

  it("lowers the budget when a product is too large and records the retry", () => {
    let s = reducer(loaded(), { type: "productTooLarge", retryWithPoints: 50_000 });
    expect(s.selection!.maximumPoints).toBe(50_000);
    s = reducer(s, { type: "requestStarted", retryFrom: 200_000 });
    expect(s.lowerDensityRetry).toEqual({ from: 200_000, to: 50_000 });
  });

  it("reports a refused display change and clears it once one applies", () => {
    let s = reducer(loaded(), { type: "displayOutcome", outcome: { status: "refused", reason: "log needs a positive minimum" } });
    expect(s.displayProblem).toBe("log needs a positive minimum");
    s = reducer(s, { type: "displayOutcome", outcome: { status: "applied" } });
    expect(s.displayProblem).toBeNull();
  });

  it("tracks the sample under the pointer and clears it on a new field", () => {
    const sample = { longitude: 85, latitude: 12, depth: 50, value: 28.4 };
    let s = reducer(loaded(), { type: "rendererEvent", event: { type: "hover", sample } });
    expect(s.hovered).toEqual(sample);
    s = shown(s, succeeded(0, 1));
    expect(s.hovered).toBeNull();
  });

  it("clears a render failure only when a field is shown again", () => {
    let s = reducer(loaded(), { type: "rendererEvent", event: { type: "renderFailed", reason: "shader" } });
    s = reducer(s, { type: "setDisplay", patch: { opacity: 0.5 } });
    expect(s.renderer.phase).toBe("failed");
    s = shown(s, succeeded(0, 1));
    expect(s.renderer).toEqual({ phase: "ok" });
  });

  it("treats a lost context and an unsupported browser as permanent", () => {
    for (const event of [
      { type: "contextLost" as const, reason: "lost" },
      { type: "unsupported" as const, reason: "no WebGL2" },
    ]) {
      let s = reducer(loaded(), { type: "rendererEvent", event });
      s = shown(s, succeeded(0, 1));
      s = reducer(s, { type: "rendererEvent", event: { type: "renderFailed", reason: "later" } });
      expect(s.renderer.phase).toBe(event.type === "contextLost" ? "lost" : "unsupported");
    }
  });

  it("leaves the field's budget alone when a marker is picked", () => {
    const before = loaded();
    const pick = { datasetVersionId: "v", platformId: "p", cycle: "1", longitude: 0, latitude: 0, observedAt: "t" };
    const after = reducer(before, { type: "rendererEvent", event: { type: "pick", marker: pick } });
    expect(after.selection).toEqual(before.selection);
  });

  it("reports a failed request without touching the shown product", () => {
    const before = shown(loaded(), succeeded(0, 1));
    const failed: RequestView = { ...succeeded(0, 1), state: "failed", product: null, failure: { code: "work_limit", message: "too big" } };
    const after = reducer(before, { type: "requestFinished", view: failed });
    expect(after.request).toEqual({ phase: "failed", failure: { code: "work_limit", message: "too big" } });
    expect(after.product).toBe(before.product);
  });
});
