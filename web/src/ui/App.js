import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// The model-field workspace (IMAP s7-model-field-layout): the field on the
// globe fills the view; selection and display controls sit in a side panel
// that becomes a drawer on narrow screens. All side effects live here; the
// reducer stays pure.
import { AppShell, Badge, Burger, Group, ScrollArea, Stack, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { ServiceError } from "../api/client";
import { decodeMarkers, decodeProfile } from "../api/observationWire";
import { decodePointField, WireError } from "../api/wire";
import { initialState, intentFor, markerQueryFor, reducer } from "../state/store";
import { Colourbar } from "./Colourbar";
import { DisplayPanel } from "./DisplayPanel";
import { HoverReadout } from "./HoverReadout";
import { ObservationPanel } from "./ObservationPanel";
import { ProfileDrawer } from "./ProfileDrawer";
import { SamplingDisclosure } from "./SamplingDisclosure";
import { SelectionPanel } from "./SelectionPanel";
import { StatusBanner } from "./StatusBanner";
/** A failure the user can act on, from whatever went wrong. */
function failureOf(error) {
    return error instanceof ServiceError
        ? { code: error.code, message: error.message }
        : error instanceof WireError
            ? { code: "unreadable_product", message: error.message }
            : { code: "network", message: "the server could not be reached" };
}
export function App({ client, createRenderer }) {
    // One renderer for the page's lifetime, from the injected factory; its
    // declared capability bounds every request the UI makes.
    const [renderer] = useState(createRenderer);
    const globeRef = useRef(null);
    const inFlight = useRef(null);
    const [state, dispatch] = useReducer(reducer, renderer.capabilities.maximumPoints, initialState);
    const [navOpen, { toggle: toggleNav }] = useDisclosure(true);
    const load = useCallback(async (selection, retryFrom) => {
        inFlight.current?.abort(); // a newer request supersedes the old one
        const controller = new AbortController();
        inFlight.current = controller;
        dispatch({ type: "requestStarted", retryFrom });
        try {
            const view = await client.pointField(intentFor(selection), controller.signal);
            if (view.state !== "succeeded" || !view.product) {
                dispatch({ type: "requestFinished", view });
                return;
            }
            const buffer = await client.productData(view.product.data.url, controller.signal);
            const arrays = decodePointField(view.product, buffer);
            if (controller.signal.aborted)
                return;
            // The product becomes the shown one only once the renderer has drawn it.
            const outcome = renderer.showPointField(view.product, arrays);
            if (outcome.status === "shown") {
                dispatch({ type: "productShown", view, shownPoints: outcome.shownPoints, hiddenMissingPoints: outcome.hiddenMissingPoints });
            }
            else if (outcome.status === "too-large") {
                dispatch({ type: "productTooLarge", retryWithPoints: outcome.retryWithPoints });
                void loadRef.current?.({ ...selection, maximumPoints: outcome.retryWithPoints }, selection.maximumPoints);
            }
            else {
                dispatch({ type: "productRefused", reason: outcome.reason });
            }
        }
        catch (error) {
            if (controller.signal.aborted)
                return;
            dispatch({ type: "requestFailed", failure: failureOf(error) });
        }
    }, [client, renderer]);
    const loadRef = useRef(load);
    loadRef.current = load;
    const stateRef = useRef(state);
    stateRef.current = state;
    // Floats for the chosen observation version, inside the field's region.
    const markersInFlight = useRef(null);
    const showFloats = useCallback(async () => {
        const query = markerQueryFor(stateRef.current);
        if (!query)
            return;
        markersInFlight.current?.abort();
        const controller = new AbortController();
        markersInFlight.current = controller;
        dispatch({ type: "markersStarted" });
        try {
            const descriptor = await client.observationMarkers(query, controller.signal);
            const buffer = await client.productData(descriptor.data.url, controller.signal);
            const markers = decodeMarkers(descriptor, buffer);
            if (controller.signal.aborted)
                return;
            const outcome = renderer.showMarkers(markers);
            dispatch(outcome.status === "shown"
                ? { type: "markersShown", count: outcome.count }
                : { type: "markersFailed", failure: { code: "unsupported_product", message: outcome.reason } });
        }
        catch (error) {
            if (!controller.signal.aborted)
                dispatch({ type: "markersFailed", failure: failureOf(error) });
        }
    }, [client, renderer]);
    // A picked float's exact profile, every variable its dataset declares.
    const pick = state.profile.pick;
    useEffect(() => {
        if (!pick)
            return;
        const version = stateRef.current.observations.versions?.find((v) => v.dataset_version_id === pick.datasetVersionId);
        const variables = version?.variables.map((v) => v.name) ?? [];
        if (variables.length === 0) {
            dispatch({ type: "profileFailed", failure: { code: "variable_unavailable", message: "this dataset declares no variables to plot" } });
            return;
        }
        const controller = new AbortController();
        (async () => {
            try {
                const descriptor = await client.observationProfile({
                    dataset_version_id: pick.datasetVersionId, platform_id: pick.platformId, cycle: pick.cycle, variables,
                }, controller.signal);
                const buffer = await client.productData(descriptor.data.url, controller.signal);
                if (!controller.signal.aborted)
                    dispatch({ type: "profileShown", profile: decodeProfile(descriptor, buffer) });
            }
            catch (error) {
                if (!controller.signal.aborted)
                    dispatch({ type: "profileFailed", failure: failureOf(error) });
            }
        })();
        return () => controller.abort(); // a newer pick supersedes this one
    }, [client, pick]);
    useEffect(() => {
        const unsubscribe = renderer.onEvent((event) => dispatch({ type: "rendererEvent", event }));
        if (globeRef.current)
            renderer.mount(globeRef.current);
        return () => {
            unsubscribe();
            renderer.dispose();
        };
    }, [renderer, load]);
    useEffect(() => {
        const controller = new AbortController();
        client.catalogue(controller.signal)
            .then((catalogue) => dispatch({ type: "catalogueLoaded", versions: catalogue.versions, observations: catalogue.observations }))
            .catch((error) => {
            if (!controller.signal.aborted) {
                dispatch({ type: "catalogueFailed", message: error instanceof ServiceError ? error.message : "the catalogue could not be reached" });
            }
        });
        return () => controller.abort();
    }, [client]);
    // Display state is declarative: every change is re-applied, and a refusal
    // (the view is left unchanged) is reported rather than hidden.
    useEffect(() => {
        dispatch({ type: "displayOutcome", outcome: renderer.applyDisplay(state.display) });
    }, [renderer, state.display]);
    const version = state.catalogue.versions.find((v) => v.id === state.selection?.versionId);
    const units = state.product?.product.variable_units
        ?? version?.variables.find((v) => v.name === state.selection?.variable)?.units ?? "";
    return (_jsxs(AppShell, { header: { height: 52 }, navbar: { width: 340, breakpoint: "sm", collapsed: { mobile: !navOpen, desktop: !navOpen } }, padding: 0, children: [_jsx(AppShell.Header, { children: _jsx(Group, { h: "100%", px: "md", justify: "space-between", children: _jsxs(Group, { gap: "sm", children: [_jsx(Burger, { opened: navOpen, onClick: toggleNav, size: "sm", "aria-label": "Toggle controls" }), _jsx(Title, { order: 1, size: "h4", children: "INCOIS 3D Ocean Viewer" }), _jsx(Badge, { variant: "light", color: "gray", children: "Prototype \u00B7 sampled model field \u00B7 observations" })] }) }) }), _jsx(AppShell.Navbar, { "aria-label": "Controls", children: _jsx(ScrollArea, { p: "md", children: _jsxs(Stack, { gap: "lg", children: [_jsx(SelectionPanel, { catalogue: state.catalogue, selection: state.selection, loading: state.request.phase === "loading", maximumPoints: state.rendererMaximumPoints, onSelectVersion: (versionId) => dispatch({ type: "selectVersion", versionId }), onEdit: (patch) => dispatch({ type: "editSelection", patch }), onShow: () => state.selection && void load(state.selection) }), _jsx(DisplayPanel, { display: state.display, fullSubsetRange: state.product?.product.full_subset_range ?? null, enabled: state.product !== null, onChange: (patch) => dispatch({ type: "setDisplay", patch }), onUseFullSubsetRange: () => dispatch({ type: "useFullSubsetRange" }), onResetCamera: () => renderer.command({ type: "resetCamera" }) }), _jsx(ObservationPanel, { observations: state.observations, canSearch: markerQueryFor(state) !== null, onSelectVersion: (versionId) => dispatch({ type: "selectObservationVersion", versionId }), onEditWindow: (patch) => dispatch({ type: "editObservationWindow", patch }), onShow: () => void showFloats() })] }) }) }), _jsxs(AppShell.Main, { style: { position: "relative", height: "calc(100dvh - 52px)" }, children: [_jsx("div", { className: "globe", ref: globeRef, "aria-label": "3D globe view" }), _jsx("div", { className: "overlay top", children: _jsx(StatusBanner, { catalogue: state.catalogue, request: state.request, renderer: state.renderer, displayProblem: state.displayProblem, hasProduct: state.product !== null }) }), state.hovered && state.product && (_jsx("div", { className: "overlay top-right", children: _jsx(HoverReadout, { sample: state.hovered, units: units, variable: state.product.product.identity.variable }) })), state.product && (_jsxs(_Fragment, { children: [_jsx("div", { className: "overlay bottom-left", children: _jsx(Colourbar, { display: state.display, units: units, variable: state.product.product.identity.variable }) }), _jsx("div", { className: "overlay bottom-right", children: _jsx(SamplingDisclosure, { product: state.product, budget: state.budget, shown: state.shown, retry: state.lowerDensityRetry, verticalExaggeration: state.display.verticalExaggeration }) })] })), _jsx(ProfileDrawer, { profile: state.profile, onClose: () => dispatch({ type: "profileClosed" }) })] })] }));
}
