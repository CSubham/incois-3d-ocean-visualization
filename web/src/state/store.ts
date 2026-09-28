// S7 application state: one reducer, semantic actions, no side effects.
//
// Selection changes produce a data request (handled outside the reducer);
// display changes are applied to the renderer as declarative state and never
// cause reprocessing.

import type { Budget, CatalogueVersion, Failure, RequestView } from "../api/client";
import type { ProductDescriptor } from "../api/wire";
import type { DisplayState, PointSample, RendererEvent } from "../renderer/contract";
import { suggestedExaggeration } from "../renderer/transform";

export interface Selection {
  versionId: string;
  variable: string;
  time: string;
  west: number; east: number; south: number; north: number;
  depthMinimum: number; depthMaximum: number;
  maximumPoints: number;
}

export type RangeSource = "full-subset" | "custom";

export interface Display extends DisplayState {
  rangeSource: RangeSource;
  exaggerationSource: "suggested" | "custom";
}

export type RequestState =
  | { phase: "idle" }
  | { phase: "loading"; retryFrom?: number }
  | { phase: "shown" }
  | { phase: "failed"; failure: Failure };

export interface State {
  catalogue: { phase: "loading" | "ready" | "failed"; versions: CatalogueVersion[]; message?: string };
  selection: Selection | null;
  request: RequestState;
  product: ProductDescriptor | null;
  budget: Budget | null;
  lowerDensityRetry: { from: number; to: number } | null;
  shown: { points: number; hiddenMissing: number } | null;
  hovered: PointSample | null;
  display: Display;
  renderer: { phase: "ok" | "unsupported" | "error"; reason?: string };
  rendererMaximumPoints: number;
}

export type Action =
  | { type: "catalogueLoaded"; versions: CatalogueVersion[] }
  | { type: "catalogueFailed"; message: string }
  | { type: "selectVersion"; versionId: string }
  | { type: "editSelection"; patch: Partial<Omit<Selection, "versionId">> }
  | { type: "requestStarted"; retryFrom?: number }
  | { type: "requestFinished"; view: RequestView }
  | { type: "requestFailed"; failure: Failure }
  | { type: "rendererEvent"; event: RendererEvent }
  | { type: "setDisplay"; patch: Partial<Omit<Display, "rangeSource" | "exaggerationSource">> }
  | { type: "useFullSubsetRange" };

export const DEFAULT_POINTS = 200_000;

export function initialState(rendererMaximumPoints: number): State {
  return {
    catalogue: { phase: "loading", versions: [] },
    selection: null,
    request: { phase: "idle" },
    product: null,
    budget: null,
    lowerDensityRetry: null,
    shown: null,
    hovered: null,
    display: {
      palette: "thermal", range: { minimum: 0, maximum: 1 }, scale: "linear",
      opacity: 1, verticalExaggeration: 100,
      rangeSource: "full-subset", exaggerationSource: "suggested",
    },
    renderer: { phase: "ok" },
    rendererMaximumPoints,
  };
}

export function defaultSelection(version: CatalogueVersion, maximumPoints: number): Selection {
  const e = version.extent;
  return {
    versionId: version.id,
    variable: version.variables[0]?.name ?? "",
    time: version.time_values?.[0] ?? e.time_start ?? "",
    west: e.west ?? 0, east: e.east ?? 0, south: e.south ?? 0, north: e.north ?? 0,
    depthMinimum: e.depth_min ?? 0, depthMaximum: e.depth_max ?? 0,
    maximumPoints: Math.min(DEFAULT_POINTS, maximumPoints),
  };
}

function suggestedFor(selection: Selection): number {
  const midLatitude = ((selection.south + selection.north) / 2) * Math.PI / 180;
  const widthKm = Math.abs(selection.east - selection.west) * 111.32 * Math.cos(midLatitude);
  const lengthKm = Math.abs(selection.north - selection.south) * 110.574;
  const depthKm = Math.abs(selection.depthMaximum - selection.depthMinimum) / 1000;
  return suggestedExaggeration(Math.max(widthKm, lengthKm), depthKm);
}

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "catalogueLoaded": {
      const first = action.versions[0];
      return {
        ...state,
        catalogue: { phase: "ready", versions: action.versions },
        selection: first ? defaultSelection(first, state.rendererMaximumPoints) : null,
      };
    }
    case "catalogueFailed":
      return { ...state, catalogue: { phase: "failed", versions: [], message: action.message } };
    case "selectVersion": {
      const version = state.catalogue.versions.find((v) => v.id === action.versionId);
      if (!version) return state;
      return { ...state, selection: defaultSelection(version, state.rendererMaximumPoints) };
    }
    case "editSelection":
      if (!state.selection) return state;
      return {
        ...state,
        selection: {
          ...state.selection, ...action.patch,
          ...(action.patch.maximumPoints !== undefined
            ? { maximumPoints: Math.min(action.patch.maximumPoints, state.rendererMaximumPoints) }
            : {}),
        },
      };
    case "requestStarted":
      return {
        ...state,
        request: { phase: "loading", retryFrom: action.retryFrom },
        lowerDensityRetry: action.retryFrom !== undefined && state.selection
          ? { from: action.retryFrom, to: state.selection.maximumPoints }
          : null,
      };
    case "requestFinished": {
      const { view } = action;
      if (view.state === "failed" || !view.product) {
        return {
          ...state,
          request: { phase: "failed", failure: view.failure ?? { code: "unknown", message: "no product was returned" } },
          budget: view.budget,
        };
      }
      const range = view.product.product.full_subset_range;
      const display = { ...state.display };
      if (display.rangeSource === "full-subset" && range.minimum !== null && range.maximum !== null) {
        display.range = { minimum: range.minimum, maximum: range.maximum };
      }
      if (display.exaggerationSource === "suggested" && state.selection) {
        display.verticalExaggeration = suggestedFor(state.selection);
      }
      if (display.scale === "log" && !(display.range.minimum > 0)) display.scale = "linear";
      return { ...state, request: { phase: "shown" }, product: view.product, budget: view.budget, display };
    }
    case "requestFailed":
      return { ...state, request: { phase: "failed", failure: action.failure } };
    case "rendererEvent": {
      const { event } = action;
      if (event.type === "ready") {
        return { ...state, shown: { points: event.shownPoints, hiddenMissing: event.hiddenMissingPoints }, hovered: null };
      }
      if (event.type === "hover") return { ...state, hovered: event.sample };
      if (event.type === "unsupported") return { ...state, renderer: { phase: "unsupported", reason: event.reason } };
      if (event.type === "error") return { ...state, renderer: { phase: "error", reason: event.reason } };
      if (event.type === "resource") {
        // Lower the budget; the controller re-requests.
        if (!state.selection) return state;
        return { ...state, selection: { ...state.selection, maximumPoints: event.retryWithPoints } };
      }
      // Marker events are handled by the observation workflow (phase 4).
      return state;
    }
    case "setDisplay": {
      const patch = action.patch;
      return {
        ...state,
        display: {
          ...state.display, ...patch,
          rangeSource: patch.range ? "custom" : state.display.rangeSource,
          exaggerationSource: patch.verticalExaggeration !== undefined ? "custom" : state.display.exaggerationSource,
        },
        renderer: state.renderer.phase === "error" ? { phase: "ok" } : state.renderer,
      };
    }
    case "useFullSubsetRange": {
      const range = state.product?.product.full_subset_range;
      if (!range || range.minimum === null || range.maximum === null) return state;
      return {
        ...state,
        display: { ...state.display, range: { minimum: range.minimum, maximum: range.maximum }, rangeSource: "full-subset" },
      };
    }
  }
}

/** The request S5 receives for the current selection. */
export function intentFor(selection: Selection) {
  return {
    dataset_version_id: selection.versionId,
    variable: selection.variable,
    time: selection.time,
    west: selection.west, east: selection.east, south: selection.south, north: selection.north,
    depth_minimum: selection.depthMinimum, depth_maximum: selection.depthMaximum,
    maximum_points: selection.maximumPoints,
  };
}
