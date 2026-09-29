// S7 state for the sea-surface viewer: one reducer, semantic actions, no
// side effects. A frame becomes the shown frame only when the renderer
// reports it drawn, so state always describes what is on screen.

import type { CatalogueVersion, Failure, MarkerQuery, ObservationVersion } from "../api/client";
import type { Extent, PaletteName, RendererEvent, ScaleKind, SurfaceSample } from "../renderer/contract";
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
  /** Stored levels, shallowest first; the first is the sea surface. */
  depths: number[];
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

/** Declarative display state (UIC-004 to UIC-006); never reprocesses data. */
export interface Display {
  palette: PaletteName;
  /** A user-set colour range; null follows the layer's automatic range. */
  customRange: Range | null;
  scale: ScaleKind;
  opacity: number;
  /** Cross-fade between consecutive real frames while stepping. */
  smooth: boolean;
}

export interface ViewerState {
  catalogue: { phase: "loading" | "ready" | "failed"; message?: string };
  /** Every stored version able to drive the view, preferred first. */
  sources: SurfaceSource[];
  source: SurfaceSource | null;
  depthIndex: number;
  display: Display;
  /** A cross-fade on screen between two real frames: its label says so. */
  transition: { from: string; to: string } | null;
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
  /** Where the camera rests; drives the detail layer. */
  view: Extent | null;
  /** S4's reduction factor for the whole-field layer and, when shown, the
   *  detail layer: source cells per delivered cell along each axis. */
  baseFactor: number;
  detail: { phase: "none" | "loading" | "shown" | "failed"; factor: number; failure?: Failure };
  arrows: boolean;
  floats: Floats;
  profile: ProfileState;
  renderer: { phase: "ok" | "unsupported" | "lost" | "failed"; reason?: string };
}

export type ViewerAction =
  | { type: "catalogueLoaded"; versions: CatalogueVersion[]; observations: ObservationVersion[] | null }
  | { type: "catalogueFailed"; message: string }
  | { type: "selectLayer"; layer: LayerKind }
  | { type: "selectSource"; versionId: string }
  | { type: "setDepth"; index: number }
  | { type: "setDisplay"; patch: Partial<Display> }
  | { type: "transitionStarted"; from: string; to: string }
  | { type: "transitionEnded" }
  | { type: "setTime"; index: number }
  | { type: "togglePlay" }
  /** Advance one step while playing; wraps to the first step. */
  | { type: "tick" }
  | { type: "frameStarted" }
  | { type: "frameShown"; layer: LayerKind; range: Range; units: string; factor: number }
  | { type: "viewChanged"; extent: Extent | null }
  | { type: "detailStarted" }
  | { type: "detailShown"; factor: number }
  | { type: "detailCleared" }
  | { type: "detailFailed"; failure: Failure }
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
    sources: [],
    source: null,
    depthIndex: 0,
    display: { palette: "thermal", customRange: null, scale: "linear", opacity: 0.92, smooth: true },
    transition: null,
    observations: [],
    layer: "temperature",
    timeIndex: 0,
    playing: false,
    frame: { phase: "idle" },
    ranges: {},
    units: {},
    probe: null,
    view: null,
    baseFactor: 1,
    detail: { phase: "none", factor: 1 },
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

/** Every gridded version able to drive the surface view, preferred first:
 *  sea temperature, then the widest area, then the most time steps. */
export function surfaceSources(versions: CatalogueVersion[]): SurfaceSource[] {
  const candidates = versions.filter((v) =>
    v.geometry === "grid" && (v.time_values?.length ?? 0) > 0 && (v.depth_values?.length ?? 0) > 0
    && v.extent.west !== null && v.extent.east !== null && v.extent.south !== null && v.extent.north !== null
    && (temperatureOf(v) !== null || currentsOf(v) !== null));
  const covered = (v: CatalogueVersion) =>
    (v.extent.east! - v.extent.west!) * (v.extent.north! - v.extent.south!);
  const score = (v: CatalogueVersion) =>
    [Number(temperatureOf(v) !== null), covered(v), v.time_values!.length, v.created_at] as const;
  candidates.sort((a, b) => {
    const [x, y] = [score(a), score(b)];
    return y[0] - x[0] || y[1] - x[1] || y[2] - x[2] || y[3].localeCompare(x[3]);
  });
  return candidates.map((best) => ({
    versionId: best.id,
    dataset: best.dataset,
    times: best.time_values!,
    depths: [...best.depth_values!].sort((a, b) => a - b),
    area: { west: best.extent.west!, east: best.extent.east!, south: best.extent.south!, north: best.extent.north! },
    temperature: temperatureOf(best),
    currents: currentsOf(best),
  }));
}

/** The preferred source, or null when none can drive the view. */
export function surfaceSource(versions: CatalogueVersion[]): SurfaceSource | null {
  return surfaceSources(versions)[0] ?? null;
}

/** "Global · 84 steps, every 3 h · 6 depths to 1000 m": what a source holds. */
export function describeSource(source: SurfaceSource): string {
  const { west, east, south, north } = source.area;
  const where = east - west >= 359 ? "Global"
    : `${Math.round(west)}–${Math.round(east)}°E, ${Math.round(south)}–${Math.round(north)}°N`;
  const times = source.times.map((t) => Date.parse(t.replace(/\.\d+$/, "") + (/[Z+-]\d*:?\d*$/.test(t) ? "" : "Z")));
  const hours = times.length > 1 ? Math.round((times[1] - times[0]) / 3_600_000) : 0;
  const cadence = times.length < 2 ? "1 step"
    : `${times.length} steps, ${hours % 24 === 0 ? (hours === 24 ? "daily" : `every ${hours / 24} days`) : `every ${hours} h`}`;
  const depths = source.depths.length > 1
    ? `${source.depths.length} depths to ${Math.round(source.depths[source.depths.length - 1])} m`
    : "sea surface";
  return `${where} · ${cadence} · ${depths}`;
}

/** The colour range in force: the user's, else the layer's automatic one. */
export function effectiveRange(state: ViewerState): Range | undefined {
  return state.display.customRange ?? state.ranges[state.layer];
}

export function available(source: SurfaceSource | null, layer: LayerKind): boolean {
  return layer === "temperature" ? source?.temperature != null : source?.currents != null;
}

/** Every float of the first observation version, over its own extent and
 *  time span (its longitudes need not share the model field's convention). */
export function floatQuery(state: ViewerState): MarkerQuery | null {
  const version = state.observations?.[0];
  const { west, east, south, north, time_start, time_end } = version?.extent ?? {};
  if (!version || west == null || east == null || south == null || north == null
      || !time_start || !time_end) return null;
  return {
    dataset_version_id: version.dataset_version_id, west, east, south, north,
    time_start, time_end,
  };
}

export function viewerReducer(state: ViewerState, action: ViewerAction): ViewerState {
  switch (action.type) {
    case "catalogueLoaded": {
      const sources = surfaceSources(action.versions);
      const source = sources[0] ?? null;
      const layer: LayerKind = available(source, "temperature") ? "temperature" : "currents";
      return {
        ...state, sources, source, layer, timeIndex: 0, depthIndex: 0, observations: action.observations,
        catalogue: source
          ? { phase: "ready" }
          : { phase: "failed", message: "no stored model version has sea temperature or currents on a regular grid" },
      };
    }
    case "catalogueFailed":
      return { ...state, catalogue: { phase: "failed", message: action.message } };
    case "selectSource": {
      const source = state.sources.find((s) => s.versionId === action.versionId);
      if (!source || source === state.source) return state;
      // A new dataset starts at its first step and surface, on fresh ranges.
      return {
        ...state, source, timeIndex: 0, depthIndex: 0, playing: false, ranges: {}, probe: null,
        layer: available(source, state.layer) ? state.layer : available(source, "temperature") ? "temperature" : "currents",
      };
    }
    case "setDepth": {
      const count = state.source?.depths.length ?? 0;
      if (action.index < 0 || action.index >= count || action.index === state.depthIndex) return state;
      // Deeper water spans a different range: the automatic range restarts.
      return { ...state, depthIndex: action.index, ranges: {}, probe: null };
    }
    case "setDisplay":
      return { ...state, display: { ...state.display, ...action.patch } };
    case "transitionStarted":
      return { ...state, transition: { from: action.from, to: action.to } };
    case "transitionEnded":
      return { ...state, transition: null };
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
        baseFactor: action.factor,
        renderer: state.renderer.phase === "failed" ? { phase: "ok" } : state.renderer,
      };
    case "frameFailed":
      return { ...state, frame: { phase: "failed", failure: action.failure }, playing: false };
    case "viewChanged":
      return { ...state, view: action.extent };
    case "detailStarted":
      return { ...state, detail: { ...state.detail, phase: "loading", failure: undefined } };
    case "detailShown":
      return { ...state, detail: { phase: "shown", factor: action.factor } };
    case "detailCleared":
      return { ...state, detail: { phase: "none", factor: 1 } };
    case "detailFailed":
      return { ...state, detail: { ...state.detail, phase: "failed", failure: action.failure } };
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
        case "view": return { ...state, view: event.extent };
        case "pick": return { ...state, profile: { phase: "loading", pick: event.marker, profile: null } };
        case "unsupported": return { ...state, renderer: { phase: "unsupported", reason: event.reason } };
        case "contextLost": return { ...state, renderer: { phase: "lost", reason: event.reason }, playing: false };
        case "renderFailed": return { ...state, renderer: { phase: "failed", reason: event.reason } };
        default: return state;
      }
    }
  }
}
