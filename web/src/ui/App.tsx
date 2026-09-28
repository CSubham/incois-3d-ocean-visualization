// The model-field workspace (IMAP s7-model-field-layout): the field on the
// globe fills the view; selection and display controls sit in a side panel
// that becomes a drawer on narrow screens. All side effects live here; the
// reducer stays pure.

import { AppShell, Badge, Burger, Group, ScrollArea, Stack, Title } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { ServiceError, type DataClient } from "../api/client";
import { decodePointField, WireError } from "../api/wire";
import type { Renderer, RendererFactory } from "../renderer/contract";
import { initialState, intentFor, reducer, type Selection } from "../state/store";
import { Colourbar } from "./Colourbar";
import { DisplayPanel } from "./DisplayPanel";
import { HoverReadout } from "./HoverReadout";
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
  const globeRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef<AbortController | null>(null);
  const [state, dispatch] = useReducer(reducer, renderer.capabilities.maximumPoints, initialState);
  const [navOpen, { toggle: toggleNav }] = useDisclosure(true);

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
    if (globeRef.current) renderer.mount(globeRef.current);
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
    <AppShell
      header={{ height: 52 }}
      navbar={{ width: 340, breakpoint: "sm", collapsed: { mobile: !navOpen, desktop: !navOpen } }}
      padding={0}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={navOpen} onClick={toggleNav} size="sm" aria-label="Toggle controls" />
            <Title order={1} size="h4">INCOIS 3D Ocean Viewer</Title>
            <Badge variant="light" color="gray">Prototype · sampled scalar field</Badge>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar aria-label="Controls">
        <ScrollArea p="md">
          <Stack gap="lg">
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
          </Stack>
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Main style={{ position: "relative", height: "calc(100dvh - 52px)" }}>
        <div className="globe" ref={globeRef} aria-label="3D globe view" />
        <div className="overlay top">
          <StatusBanner catalogue={state.catalogue} request={state.request} renderer={state.renderer} hasProduct={state.product !== null} />
        </div>
        {state.hovered && state.product && (
          <div className="overlay top-right">
            <HoverReadout sample={state.hovered} units={units} variable={state.product.product.identity.variable} />
          </div>
        )}
        {state.product && (
          <>
            <div className="overlay bottom-left">
              <Colourbar display={state.display} units={units} variable={state.product.product.identity.variable} />
            </div>
            <div className="overlay bottom-right">
              <SamplingDisclosure product={state.product} budget={state.budget} shown={state.shown}
                retry={state.lowerDensityRetry} verticalExaggeration={state.display.verticalExaggeration} />
            </div>
          </>
        )}
      </AppShell.Main>
    </AppShell>
  );
}
