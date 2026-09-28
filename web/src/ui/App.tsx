// The model-field workspace (IMAP s7-model-field-layout): selection and
// display controls beside the 3D view, with sampling disclosure and status.
// All side effects live here; the reducer stays pure.

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { ServiceError, type DataClient } from "../api/client";
import { decodePointField, WireError } from "../api/wire";
import type { Renderer, RendererFactory } from "../renderer/contract";
import { initialState, intentFor, reducer, type Selection } from "../state/store";
import { Colourbar } from "./Colourbar";
import { DisplayPanel } from "./DisplayPanel";
import { SamplingDisclosure } from "./SamplingDisclosure";
import { SelectionPanel } from "./SelectionPanel";
import { StatusBanner } from "./StatusBanner";

interface Props {
  client: DataClient;
  createRenderer: RendererFactory;
}

export function App({ client, createRenderer }: Props) {
  // One renderer for the page's lifetime, from the injected factory; its
  // declared capability bounds every request the UI makes.
  const [renderer] = useState<Renderer>(createRenderer);
  const viewportRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef<AbortController | null>(null);
  const [state, dispatch] = useReducer(
    reducer, renderer.capabilities.maximumPoints, initialState);

  const load = useCallback(async (selection: Selection, retryFrom?: number) => {
    inFlight.current?.abort();   // a newer request supersedes the old one
    const controller = new AbortController();
    inFlight.current = controller;
    dispatch({ type: "requestStarted", retryFrom });
    try {
      const view = await client.pointField(intentFor(selection), controller.signal);
      if (view.state === "succeeded" && view.product) {
        const buffer = await client.productData(view.product.data.url, controller.signal);
        const arrays = decodePointField(view.product, buffer);
        if (controller.signal.aborted) return;
        dispatch({ type: "requestFinished", view });
        renderer.showPointField(view.product, arrays);
      } else {
        dispatch({ type: "requestFinished", view });
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      const failure = error instanceof ServiceError
        ? { code: error.code, message: error.message }
        : error instanceof WireError
          ? { code: "unreadable_product", message: error.message }
          : { code: "network", message: "the server could not be reached" };
      dispatch({ type: "requestFailed", failure });
    }
  }, [client, renderer]);

  const selectionRef = useRef<Selection | null>(null);
  selectionRef.current = state.selection;
  useEffect(() => {
    const unsubscribe = renderer.onEvent((event) => {
      dispatch({ type: "rendererEvent", event });
      const selection = selectionRef.current;
      if (event.type === "resource" && selection) {
        void load({ ...selection, maximumPoints: event.retryWithPoints }, selection.maximumPoints);
      }
    });
    if (viewportRef.current) renderer.mount(viewportRef.current);
    return () => {
      unsubscribe();
      renderer.dispose();
    };
  }, [renderer, load]);

  useEffect(() => {
    const controller = new AbortController();
    client.catalogue(controller.signal)
      .then((versions) => dispatch({ type: "catalogueLoaded", versions }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          dispatch({ type: "catalogueFailed", message: error instanceof ServiceError ? error.message : "the catalogue could not be reached" });
        }
      });
    return () => controller.abort();
  }, [client]);

  // Display state is declarative: every change is simply re-applied.
  useEffect(() => { renderer.applyDisplay(state.display); }, [renderer, state.display]);

  const version = state.catalogue.versions.find((v) => v.id === state.selection?.versionId);
  const units = state.product?.product.variable_units
    ?? version?.variables.find((v) => v.name === state.selection?.variable)?.units ?? "";

  return (
    <div className="workspace">
      <aside className="controls" aria-label="Controls">
        <header>
          <h1>Ocean model viewer</h1>
          <p className="subtitle">Sampled 3D scalar field · prototype</p>
        </header>
        <SelectionPanel
          catalogue={state.catalogue}
          selection={state.selection}
          loading={state.request.phase === "loading"}
          maximumPoints={state.rendererMaximumPoints}
          onSelectVersion={(versionId) => dispatch({ type: "selectVersion", versionId })}
          onEdit={(patch) => dispatch({ type: "editSelection", patch })}
          onShow={() => state.selection && void load(state.selection)}
        />
        <DisplayPanel
          display={state.display}
          fullSubsetRange={state.product?.product.full_subset_range ?? null}
          enabled={state.product !== null}
          onChange={(patch) => dispatch({ type: "setDisplay", patch })}
          onUseFullSubsetRange={() => dispatch({ type: "useFullSubsetRange" })}
          onResetCamera={() => renderer.command({ type: "resetCamera" })}
        />
      </aside>
      <main className="view">
        <div className="viewport" ref={viewportRef} aria-label="3D view" />
        <StatusBanner catalogue={state.catalogue} request={state.request} renderer={state.renderer} hasProduct={state.product !== null} />
        {state.product && (
          <div className="overlay">
            <Colourbar display={state.display} units={units} variable={state.product.product.identity.variable} />
            <SamplingDisclosure
              product={state.product}
              budget={state.budget}
              shown={state.shown}
              retry={state.lowerDensityRetry}
              verticalExaggeration={state.display.verticalExaggeration}
            />
          </div>
        )}
      </main>
    </div>
  );
}
