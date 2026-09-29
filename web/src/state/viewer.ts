// S7 state for the sea-surface viewer: one reducer, semantic actions, no
// side effects. A frame becomes the shown frame only when the renderer
// reports it drawn, so state always describes what is on screen.

import type { CatalogueVersion, Failure, MarkerQuery, ObservationVersion } from "../api/client";
import type { RendererEvent, SurfaceSample } from "../renderer/contract";
import type { ProfileState } from "./store";

export type LayerKind = "temperature" | "currents";

/** Variable names S3 uses for sea temperature and current components, by
 *  source. Matched in order until the catalogue carries CF standard names. */
const TEMPERATURE_NAMES = ["water_temp", "thetao", "temperature", "sea_water_temperature"];
const CURRENT_PAIRS: [string, string][] = [["water_u", "water_v"], ["uo", "vo"], ["u", "v"]];

/** A stored model version that can drive the surface views. */
export interface SurfaceSource {
  versionId: string;
  dataset: string;
  times: string[];
  /** The shallowest stored level: the sea surface for this viewer. */
  depth: number;
  area: { west: number; east: number; south: number; north: number };
  temperature: string | null;
  currents: { eastward: string; northward: string } | null;
}

export interface Range { minimum: number; maximum: number }

export interface Floats {
  enabled: boolean;
  phase: "idle" | "loading" | "shown" | "failed";
  count: number;
  failure?: Failure;
}

export interface ViewerState {
  catalogue: { phase: "loading" | "ready" | "failed"; message?: string };
  source: SurfaceSource | null;
  observations: ObservationVersion[] | null;
  layer: LayerKind;
  timeIndex: number;
  playing: boolean;
  frame: { phase: "idle" | "loading" | "shown" | "failed"; failure?: Failure };
  /** Fixed per layer from its first shown frame, so an animation keeps one
   *  colour scale and colours stay comparable across time steps. */
  ranges: Partial<Record<LayerKind, Range>>;
  units: Partial<Record<LayerKind, string>>;
  probe: SurfaceSample | null;
  arrows: boolean;
  floats: Floats;
  profile: ProfileState;
  renderer: { phase: "ok" | "unsupported" | "lost" | "failed"; reason?: string };
}

export type ViewerAction =
  | { type: "catalogueLoaded"; versions: CatalogueVersion[]; observations: ObservationVersion[] | null }
  | { type: "catalogueFailed"; message: string }
  | { type: "selectLayer"; layer: LayerKind }
  | { type: "setTime"; index: number }
  | { type: "togglePlay" }
  /** Advance one step while playing; wraps to the first step. */
  | { type: "tick" }
  | { type: "frameStarted" }
  | { type: "frameShown"; layer: LayerKind; range: Range; units: string }
  | { type: "frameFailed"; failure: Failure }
  | { type: "toggleArrows" }
  | { type: "toggleFloats" }
  | { type: "floatsStarted" }
  | { type: "floatsShown"; count: number }
  | { type: "floatsFailed"; failure: Failure }
  | { type: "profileShown"; profile: NonNullable<ProfileState["profile"]> }
  | { type: "profileFailed"; failure: Failure }
  | { type: "profileClosed" }
  | { type: "rendererEvent"; event: RendererEvent };

export function initialViewerState(): ViewerState {
  return {
    catalogue: { phase: "loading" },
    source: null,
    observations: [],
    layer: "temperature",
    timeIndex: 0,
    playing: false,
    frame: { phase: "idle" },
    ranges: {},
    units: {},
    probe: null,
    arrows: true,
    floats: { enabled: false, phase: "idle", count: 0 },
    profile: { phase: "closed", pick: null, profile: null },
    renderer: { phase: "ok" },
  };
}

function temperatureOf(version: CatalogueVersion): string | null {
  const names = new Set(version.variables.map((v) => v.name));
  return TEMPERATURE_NAMES.find((name) => names.has(name)) ?? null;
}

function currentsOf(version: CatalogueVersion): SurfaceSource["currents"] {
  const names = new Set(version.variables.map((v) => v.name));
  const pair = CURRENT_PAIRS.find(([u, v]) => names.has(u) && names.has(v));
  return pair ? { eastward: pair[0], northward: pair[1] } : null;
}

/** The gridded version best suited to the surface views: both layers first,
 *  then the most time steps, then the newest. */
export function surfaceSource(versions: CatalogueVersion[]): SurfaceSource | null {
  const candidates = versions.filter((v) =>
    v.geometry === "grid" && (v.time_values?.length ?? 0) > 0 && (v.depth_values?.length ?? 0) > 0
    && v.extent.west !== null && v.extent.east !== null && v.extent.south !== null && v.extent.north !== null
    && (temperatureOf(v) !== null || currentsOf(v) !== null));
  const score = (v: CatalogueVersion) =>
    [Number(temperatureOf(v) !== null) + Number(currentsOf(v) !== null), v.time_values!.length, v.created_at] as const;
  candidates.sort((a, b) => {
    const [x, y] = [score(a), score(b)];
    return y[0] - x[0] || y[1] - x[1] || y[2].localeCompare(x[2]);
  });
  const best = candidates[0];
  if (!best) return null;
  return {
    versionId: best.id,
    dataset: best.dataset,
    times: best.time_values!,
    depth: Math.min(...best.depth_values!),
    area: { west: best.extent.west!, east: best.extent.east!, south: best.extent.south!, north: best.extent.north! },
    temperature: temperatureOf(best),
    currents: currentsOf(best),
  };
}

export function available(source: SurfaceSource | null, layer: LayerKind): boolean {
  return layer === "temperature" ? source?.temperature != null : source?.currents != null;
}

/** Floats inside the surface area, over the observation version's own time span. */
export function floatQuery(state: ViewerState): MarkerQuery | null {
  const version = state.observations?.[0];
  const area = state.source?.area;
  if (!version || !area || !version.extent.time_start || !version.extent.time_end) return null;
  return {
    dataset_version_id: version.dataset_version_id, ...area,
    time_start: version.extent.time_start, time_end: version.extent.time_end,
  };
}

export function viewerReducer(state: ViewerState, action: ViewerAction): ViewerState {
  switch (action.type) {
    case "catalogueLoaded": {
      const source = surfaceSource(action.versions);
      const layer: LayerKind = available(source, "temperature") ? "temperature" : "currents";
      return {
        ...state, source, layer, timeIndex: 0, observations: action.observations,
        catalogue: source
          ? { phase: "ready" }
          : { phase: "failed", message: "no stored model version has sea temperature or currents on a regular grid" },
      };
    }
    case "catalogueFailed":
      return { ...state, catalogue: { phase: "failed", message: action.message } };
    case "selectLayer":
      return available(state.source, action.layer) ? { ...state, layer: action.layer, probe: null } : state;
    case "setTime": {
      const count = state.source?.times.length ?? 0;
      if (action.index < 0 || action.index >= count) return state;
      return { ...state, timeIndex: action.index };
    }
    case "togglePlay":
      return { ...state, playing: !state.playing && (state.source?.times.length ?? 0) > 1 };
    case "tick": {
      const count = state.source?.times.length ?? 0;
      return state.playing && count > 1 ? { ...state, timeIndex: (state.timeIndex + 1) % count } : state;
    }
    case "frameStarted":
      return { ...state, frame: { phase: "loading" } };
    case "frameShown":
      return {
        ...state, frame: { phase: "shown" },
        ranges: { ...state.ranges, [action.layer]: state.ranges[action.layer] ?? action.range },
        units: { ...state.units, [action.layer]: action.units },
        renderer: state.renderer.phase === "failed" ? { phase: "ok" } : state.renderer,
      };
    case "frameFailed":
      return { ...state, frame: { phase: "failed", failure: action.failure }, playing: false };
    case "toggleArrows":
      return { ...state, arrows: !state.arrows };
    case "toggleFloats":
      return { ...state, floats: { enabled: !state.floats.enabled, phase: "idle", count: 0 } };
    case "floatsStarted":
      return { ...state, floats: { ...state.floats, phase: "loading", failure: undefined } };
    case "floatsShown":
      return { ...state, floats: { ...state.floats, phase: "shown", count: action.count } };
    case "floatsFailed":
      return { ...state, floats: { ...state.floats, phase: "failed", failure: action.failure } };
    case "profileShown":
      return { ...state, profile: { ...state.profile, phase: "shown", profile: action.profile } };
    case "profileFailed":
      return { ...state, profile: { ...state.profile, phase: "failed", failure: action.failure } };
    case "profileClosed":
      return { ...state, profile: { phase: "closed", pick: null, profile: null } };
    case "rendererEvent": {
      const { event } = action;
      switch (event.type) {
        case "probe": return { ...state, probe: event.sample };
        case "pick": return { ...state, profile: { phase: "loading", pick: event.marker, profile: null } };
        case "unsupported": return { ...state, renderer: { phase: "unsupported", reason: event.reason } };
        case "contextLost": return { ...state, renderer: { phase: "lost", reason: event.reason }, playing: false };
        case "renderFailed": return { ...state, renderer: { phase: "failed", reason: event.reason } };
        default: return state;
      }
    }
  }
}
