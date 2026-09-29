// S7 application state: one reducer, semantic actions, no side effects.
//
// Selection changes produce a data request (handled outside the reducer);
// display changes are applied to the renderer as declarative state and never
// cause reprocessing. A product becomes the shown product only when the
// renderer reports it shown, so state always describes what is on screen.
import { depthUnitsToKm, suggestedExaggeration } from "../renderer/transform";
export const DEFAULT_POINTS = 200_000;
export function initialState(rendererMaximumPoints) {
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
        observations: { versions: [], versionId: null, timeStart: "", timeEnd: "", phase: "idle", count: 0 },
        profile: { phase: "closed", pick: null, profile: null },
    };
}
function observationDefaults(version) {
    return {
        versionId: version?.dataset_version_id ?? null,
        timeStart: version?.extent.time_start ?? "",
        timeEnd: version?.extent.time_end ?? "",
    };
}
/** Markers for the chosen observation version, inside the model field's region
 *  when one is selected, else the version's own extent. */
export function markerQueryFor(state) {
    const obs = state.observations;
    const version = obs.versions?.find((v) => v.dataset_version_id === obs.versionId);
    if (!version || !obs.timeStart || !obs.timeEnd)
        return null;
    const region = state.selection ?? {
        west: version.extent.west ?? -180, east: version.extent.east ?? 180,
        south: version.extent.south ?? -90, north: version.extent.north ?? 90,
    };
    return {
        dataset_version_id: version.dataset_version_id,
        west: region.west, east: region.east, south: region.south, north: region.north,
        time_start: obs.timeStart, time_end: obs.timeEnd,
    };
}
export function defaultSelection(version, maximumPoints) {
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
function suggestedFor(selection, depthUnits) {
    const kmPerUnit = depthUnitsToKm(depthUnits);
    if (kmPerUnit === undefined)
        return null;
    const midLatitude = ((selection.south + selection.north) / 2) * Math.PI / 180;
    const widthKm = Math.abs(selection.east - selection.west) * 111.32 * Math.cos(midLatitude);
    const lengthKm = Math.abs(selection.north - selection.south) * 110.574;
    const depthKm = Math.abs(selection.depthMaximum - selection.depthMinimum) * kmPerUnit;
    return suggestedExaggeration(Math.max(widthKm, lengthKm), depthKm);
}
export function reducer(state, action) {
    switch (action.type) {
        case "catalogueLoaded": {
            const first = action.versions[0];
            const observations = action.observations === undefined ? [] : action.observations;
            return {
                ...state,
                catalogue: { phase: "ready", versions: action.versions },
                selection: first ? defaultSelection(first, state.rendererMaximumPoints) : null,
                observations: { ...state.observations, versions: observations, ...observationDefaults(observations?.[0]) },
            };
        }
        case "catalogueFailed":
            return { ...state, catalogue: { phase: "failed", versions: [], message: action.message } };
        case "selectVersion": {
            const version = state.catalogue.versions.find((v) => v.id === action.versionId);
            if (!version)
                return state;
            return { ...state, selection: defaultSelection(version, state.rendererMaximumPoints) };
        }
        case "editSelection":
            if (!state.selection)
                return state;
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
            if (!view.product)
                return state;
            const product = view.product.product;
            const range = product.full_subset_range;
            const display = { ...state.display };
            if (display.rangeSource === "full-subset" && range.minimum !== null && range.maximum !== null) {
                display.range = { minimum: range.minimum, maximum: range.maximum };
            }
            if (display.exaggerationSource === "suggested" && state.selection) {
                const suggested = suggestedFor(state.selection, product.coordinates.units.depth);
                if (suggested !== null)
                    display.verticalExaggeration = suggested;
            }
            if (display.scale === "log" && !(display.range.minimum > 0))
                display.scale = "linear";
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
            if (!state.selection)
                return state;
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
                    if (state.renderer.phase === "unsupported" || state.renderer.phase === "lost")
                        return state;
                    return { ...state, renderer: { phase: "failed", reason: event.reason } };
                case "pick":
                    // An exact profile identity: the controller fetches that profile.
                    return { ...state, profile: { phase: "loading", pick: event.marker, profile: null } };
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
            if (!range || range.minimum === null || range.maximum === null)
                return state;
            return {
                ...state,
                display: { ...state.display, range: { minimum: range.minimum, maximum: range.maximum }, rangeSource: "full-subset" },
            };
        }
        case "selectObservationVersion": {
            const version = state.observations.versions?.find((v) => v.dataset_version_id === action.versionId);
            if (!version)
                return state;
            return { ...state, observations: { ...state.observations, ...observationDefaults(version), phase: "idle", count: 0 } };
        }
        case "editObservationWindow":
            return { ...state, observations: { ...state.observations, ...action.patch } };
        case "markersStarted":
            return { ...state, observations: { ...state.observations, phase: "loading", failure: undefined } };
        case "markersShown":
            return { ...state, observations: { ...state.observations, phase: "shown", count: action.count, failure: undefined } };
        case "markersFailed":
            return { ...state, observations: { ...state.observations, phase: "failed", failure: action.failure } };
        case "profileShown":
            if (state.profile.phase === "closed")
                return state;
            return { ...state, profile: { ...state.profile, phase: "shown", profile: action.profile, failure: undefined } };
        case "profileFailed":
            if (state.profile.phase === "closed")
                return state;
            return { ...state, profile: { ...state.profile, phase: "failed", failure: action.failure } };
        case "profileClosed":
            return { ...state, profile: { phase: "closed", pick: null, profile: null } };
    }
}
/** The request S5 receives for the current selection. */
export function intentFor(selection) {
    return {
        dataset_version_id: selection.versionId,
        variable: selection.variable,
        time: selection.time,
        west: selection.west, east: selection.east, south: selection.south, north: selection.north,
        depth_minimum: selection.depthMinimum, depth_maximum: selection.depthMaximum,
        maximum_points: selection.maximumPoints,
    };
}
