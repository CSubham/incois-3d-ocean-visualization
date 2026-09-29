import { describe, expect, it } from "vitest";

import type { CatalogueVersion } from "../api/client";
import { floatQuery, initialViewerState, surfaceSource, viewerReducer } from "./viewer";

function version(id: string, variables: string[], times = 8, created = "2026-09-29T00:00:00Z"): CatalogueVersion {
  return {
    id, dataset: "GLBy0.08_expt_93.0", geometry: "grid",
    variables: variables.map((name) => ({ name, units: null })),
    depth_levels: 1, time_steps: times,
    extent: { time_start: null, time_end: null, depth_min: 0, depth_max: 0, west: 30, east: 120, south: -30, north: 30 },
    time_values: Array.from({ length: times }, (_, i) => `2024-09-05T0${i}:00:00`),
    depth_values: [0, 10],
    created_at: created,
  };
}

describe("choosing the surface source", () => {
  it("prefers temperature, then the widest area, then more time steps", () => {
    const regional = version("regional", ["water_temp", "water_u", "water_v"], 4);
    const global = { ...version("global", ["water_temp"], 8), extent: { ...regional.extent, west: -179.92, east: 180, south: -80, north: 90 } };
    const source = surfaceSource([regional, global, version("currents", ["water_u", "water_v"], 30)]);
    expect(source?.versionId).toBe("global");
    expect(source?.temperature).toBe("water_temp");
    expect(source?.depth).toBe(0);
    expect(surfaceSource([version("a", ["water_temp"], 4), version("b", ["water_temp"], 8)])?.versionId).toBe("b");
  });

  it("reports when nothing can drive the viewer", () => {
    const state = viewerReducer(initialViewerState(), { type: "catalogueLoaded", versions: [version("argo", ["TEMP"])], observations: [] });
    expect(state.catalogue.phase).toBe("failed");
  });
});

describe("the viewer reducer", () => {
  const loaded = viewerReducer(initialViewerState(), {
    type: "catalogueLoaded", versions: [version("both", ["water_temp", "water_u", "water_v"], 3)], observations: null,
  });

  it("plays only across more than one step and wraps", () => {
    let state = viewerReducer(loaded, { type: "togglePlay" });
    expect(state.playing).toBe(true);
    state = viewerReducer(viewerReducer(viewerReducer(state, { type: "tick" }), { type: "tick" }), { type: "tick" });
    expect(state.timeIndex).toBe(0);
  });

  it("keeps a layer's first colour range for the whole animation", () => {
    let state = viewerReducer(loaded, { type: "frameShown", layer: "temperature", range: { minimum: 20, maximum: 30 }, units: "degC", factor: 1 });
    state = viewerReducer(state, { type: "frameShown", layer: "temperature", range: { minimum: 0, maximum: 99 }, units: "degC", factor: 1 });
    expect(state.ranges.temperature).toEqual({ minimum: 20, maximum: 30 });
  });

  it("stops playing when a frame fails", () => {
    const playing = viewerReducer(loaded, { type: "togglePlay" });
    const failed = viewerReducer(playing, { type: "frameFailed", failure: { code: "network", message: "down" } });
    expect(failed.playing).toBe(false);
  });

  it("refuses a layer the source does not carry", () => {
    const tempOnly = viewerReducer(initialViewerState(), { type: "catalogueLoaded", versions: [version("t", ["water_temp"])], observations: null });
    expect(viewerReducer(tempOnly, { type: "selectLayer", layer: "currents" }).layer).toBe("temperature");
  });

  it("asks for floats only when observations exist", () => {
    expect(floatQuery(loaded)).toBeNull();
  });
});
