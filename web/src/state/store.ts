// S7 application state: one reducer, semantic actions, no side effects.
//
// Selection changes produce a data request (handled outside the reducer);
// display changes are applied to the renderer as declarative state and never
// cause reprocessing. A product becomes the shown product only when the
// renderer reports it shown, so state always describes what is on screen.

import type { Budget, CatalogueVersion, Failure, RequestView } from "../api/client";
import type { ProductDescriptor } from "../api/wire";
import type { DisplayOutcome, DisplayState, PointSample, RendererEvent } from "../renderer/contract";
import { depthUnitsToKm, suggestedExaggeration } from "../renderer/transform";

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
  /** Why the last display change was not applied; the view is unchanged. */
  displayProblem: string | null;
  /** "unsupported" and "lost" are permanent; "failed" clears when a field is shown. */
  renderer: { phase: "ok" | "unsupported" | "lost" | "failed"; reason?: string };
  rendererMaximumPoints: number;
}

export type Action =
  | { type: "catalogueLoaded"; versions: CatalogueVersion[] }
  | { type: "catalogueFailed"; message: string }
  | { type: "selectVersion"; versionId: string }
  | { type: "editSelection"; patch: Partial<Omit<Selection, "versionId">> }
  | { type: "requestStarted"; retryFrom?: number }
  /** A request that ended without a product to show. */
  | { type: "requestFinished"; view: RequestView }
  | { type: "requestFailed"; failure: Failure }
  /** The renderer drew this product; it is now the shown product. */
  | { type: "productShown"; view: RequestView; shownPoints: number; hiddenMissingPoints: number }
  /** The renderer refused the product; the previous one is still shown. */
  | { type: "productRefused"; reason: string }
  /** The renderer asks for a lower point budget; the controller re-requests. */
  | { type: "productTooLarge"; retryWithPoints: number }
  | { type: "displayOutcome"; outcome: DisplayOutcome }
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
    displayProblem: null,
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

/** A readable exaggeration, from the product's declared depth units; null
 *  when the units are unknown, so no unit is assumed. */
function suggestedFor(selection: Selection, depthUnits: string | null | undefined): number | null {
  const kmPerUnit = depthUnitsToKm(depthUnits);
  if (kmPerUnit === undefined) return null;
  const midLatitude = ((selection.south + selection.north) / 2) * Math.PI / 180;
  const widthKm = Math.abs(selection.east - selection.west) * 111.32 * Math.cos(midLatitude);
  const lengthKm = Math.abs(selection.north - selection.south) * 110.574;
  const depthKm = Math.abs(selection.depthMaximum - selection.depthMinimum) * kmPerUnit;
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
      return {
        ...state,
        request: { phase: "failed", failure: view.failure ?? { code: "unknown", message: "no product was returned" } },
      };
    }
    case "requestFailed":
      return { ...state, request: { phase: "failed", failure: action.failure } };
    case "productShown": {
      const { view } = action;
      if (!view.product) return state;
      const product = view.product.product;
      const range = product.full_subset_range;
      const display = { ...state.display };
      if (display.rangeSource === "full-subset" && range.minimum !== null && range.maximum !== null) {
        display.range = { minimum: range.minimum, maximum: range.maximum };
      }
      if (display.exaggerationSource === "suggested" && state.selection) {
        const suggested = suggestedFor(state.selection, product.coordinates.units.depth);
        if (suggested !== null) display.verticalExaggeration = suggested;
      }
      if (display.scale === "log" && !(display.range.minimum > 0)) display.scale = "linear";
      return {
        ...state,
        request: { phase: "shown" },
        product: view.product,
        budget: view.budget,
        shown: { points: action.shownPoints, hiddenMissing: action.hiddenMissingPoints },
        hovered: null,
        display,
        renderer: state.renderer.phase === "failed" ? { phase: "ok" } : state.renderer,
      };
    }
    case "productRefused":
      return {
        ...state,
        request: { phase: "failed", failure: { code: "unsupported_product", message: action.reason } },
      };
    case "productTooLarge":
      if (!state.selection) return state;
      return { ...state, selection: { ...state.selection, maximumPoints: action.retryWithPoints } };
    case "displayOutcome":
      return {
        ...state,
        displayProblem: action.outcome.status === "refused" ? action.outcome.reason : null,
      };
    case "rendererEvent": {
      const { event } = action;
      switch (event.type) {
        case "hover":
          return { ...state, hovered: event.sample };
        case "unsupported":
          return { ...state, renderer: { phase: "unsupported", reason: event.reason } };
        case "contextLost":
          return { ...state, renderer: { phase: "lost", reason: event.reason } };
        case "renderFailed":
          if (state.renderer.phase === "unsupported" || state.renderer.phase === "lost") return state;
          return { ...state, renderer: { phase: "failed", reason: event.reason } };
        case "pick":
          // Handled by the observation workflow (phase 4).
          return state;
      }
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
