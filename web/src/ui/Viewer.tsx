// The sea-surface viewer (S7): model layers draped on the globe, a time bar
// that animates the stored time steps, Argo floats with their profiles, and
// an exact readout of the cell under the pointer. All side effects live
// here; the reducer stays pure and the renderer is reached only through its
// facade.

import {
  ActionIcon, Alert, Badge, Group, Loader, Paper, Slider, Stack, Switch, Text, Title,
} from "@mantine/core";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { ServiceError, type DataClient } from "../api/client";
import { decodeMarkers, decodeProfile } from "../api/observationWire";
import { decodeSlice, decodeVector } from "../api/sliceWire";
import { WireError } from "../api/wire";
import { cssGradient } from "../renderer/colour";
import type { Extent, PaletteName, Renderer, RendererFactory, SurfaceField } from "../renderer/contract";
import { robustRange } from "../renderer/surface";
import { detailExtent } from "../state/detail";
import {
  available, floatQuery, initialViewerState, viewerReducer, type LayerKind, type Range,
  type SurfaceSource,
} from "../state/viewer";
import { formatUtc } from "./format";
import { ProfileDrawer } from "./ProfileDrawer";
import { displayUnits, flowBearing, formatPosition } from "./surfaceFormat";

interface Props {
  client: DataClient;
  createRenderer: RendererFactory;
}

const LAYERS: Record<LayerKind, { title: string; palette: PaletteName }> = {
  temperature: { title: "Sea surface temperature", palette: "thermal" },
  currents: { title: "Surface current speed", palette: "speed" },
};

/** Seconds each time step stays on screen while playing. */
const STEP_MS = 900;
/** Decoded frames kept in memory; a current frame is about 30 MB. */
const CACHED_FRAMES = 12;

interface Frame {
  field: SurfaceField;
  range: Range | null;
  /** S4's reduction factor: source cells per delivered cell along each axis. */
  factor: number;
}

function failureOf(error: unknown) {
  return error instanceof ServiceError
    ? { code: error.code, message: error.message }
    : error instanceof WireError
      ? { code: "unreadable_product", message: error.message }
      : { code: "network", message: "the server could not be reached" };
}

export function Viewer({ client, createRenderer }: Props) {
  const [renderer] = useState<Renderer>(createRenderer);
  const globeRef = useRef<HTMLDivElement>(null);
  const [state, dispatch] = useReducer(viewerReducer, undefined, initialViewerState);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Frames by layer and time. Promises are cached so a frame requested twice
  // (shown, then prefetched) is fetched once.
  const frames = useRef(new Map<string, Promise<Frame>>());
  const frame = useCallback((source: SurfaceSource, layer: LayerKind, time: string,
                             extent: Extent, budget: number): Promise<Frame> => {
    const key = `${source.versionId}|${layer}|${time}|${extent.west},${extent.east},${extent.south},${extent.north}|${budget}`;
    const cached = frames.current.get(key);
    if (cached) return cached;
    const window = { dataset_version_id: source.versionId, time, depth: source.depth, ...extent };
    const loading = (async (): Promise<Frame> => {
      if (layer === "temperature") {
        const descriptor = await client.depthSlice(window, source.temperature!, budget);
        const arrays = decodeSlice(descriptor, await client.productData(descriptor.data.url));
        return {
          field: { ...arrays, units: descriptor.product.variable_units },
          range: robustRange(arrays.values, arrays.missingValueMask),
          factor: descriptor.product.reduction?.factor ?? 1,
        };
      }
      const { eastward, northward } = source.currents!;
      const descriptor = await client.vectorSlice(window, eastward, northward);
      const arrays = decodeVector(descriptor, await client.productData(descriptor.data.url));
      const range = robustRange(arrays.values, arrays.missingValueMask);
      return {
        field: {
          longitude: arrays.longitude, latitude: arrays.latitude, values: arrays.values,
          missingValueMask: arrays.missingValueMask, units: descriptor.product.units,
          components: { eastward: arrays.eastward, northward: arrays.northward },
        },
        // Speed starts at still water, whatever the slowest cell happens to be.
        range: range && { minimum: 0, maximum: range.maximum },
        factor: 1,
      };
    })();
    loading.catch(() => frames.current.delete(key));   // a failure is retried next time
    frames.current.set(key, loading);
    while (frames.current.size > CACHED_FRAMES) {
      frames.current.delete(frames.current.keys().next().value!);
    }
    return loading;
  }, [client]);

  // Mount once; the renderer lives as long as the page.
  useEffect(() => {
    const unsubscribe = renderer.onEvent((event) => dispatch({ type: "rendererEvent", event }));
    if (globeRef.current) renderer.mount(globeRef.current);
    return () => {
      unsubscribe();
      renderer.dispose();
    };
  }, [renderer]);

  useEffect(() => {
    const controller = new AbortController();
    client.catalogue(controller.signal)
      .then((catalogue) => dispatch({
        type: "catalogueLoaded", versions: catalogue.versions, observations: catalogue.observations,
      }))
      .catch((error) => {
        if (!controller.signal.aborted) {
          dispatch({ type: "catalogueFailed", message: error instanceof ServiceError ? error.message : "the catalogue could not be reached" });
        }
      });
    return () => controller.abort();
  }, [client]);

  const { source, layer, timeIndex } = state;
  useEffect(() => {
    if (source) renderer.command({ type: "flyTo", ...source.area });
  }, [renderer, source]);

  // The view budget S4 fits every layer to: this renderer's declared figure.
  const budget = renderer.capabilities.maximumSurfaceCells;

  // The whole field at the chosen time, fitted to the budget; a newer choice
  // supersedes it.
  const shownSequence = useRef(0);
  useEffect(() => {
    if (!source || !available(source, layer)) return;
    const sequence = ++shownSequence.current;
    const time = source.times[timeIndex];
    dispatch({ type: "frameStarted" });
    (async () => {
      try {
        const loaded = await frame(source, layer, time, source.area, budget);
        if (sequence !== shownSequence.current) return;
        const range = stateRef.current.ranges[layer] ?? loaded.range ?? { minimum: 0, maximum: 1 };
        const outcome = await renderer.showSurface(loaded.field, { palette: LAYERS[layer].palette, range, scale: "linear" }, "base");
        if (sequence !== shownSequence.current || outcome.status === "superseded") return;
        if (outcome.status === "refused") {
          dispatch({ type: "frameFailed", failure: { code: "unsupported_product", message: outcome.reason } });
          return;
        }
        dispatch({ type: "frameShown", layer, range, units: loaded.field.units, factor: loaded.factor });
        // Fetch the next step ahead so playback does not wait on the network.
        const next = source.times[(timeIndex + 1) % source.times.length];
        void frame(source, layer, next, source.area, budget).catch(() => undefined);
      } catch (error) {
        if (sequence === shownSequence.current) dispatch({ type: "frameFailed", failure: failureOf(error) });
      }
    })();
  }, [renderer, frame, budget, source, layer, timeIndex]);

  // The part in view at finer resolution, when the whole-field layer is
  // coarser than the source and most of the field is out of view.
  const detail = useMemo(
    () => (source ? detailExtent(source.area, state.view, state.baseFactor) : null),
    [source, state.view, state.baseFactor]);
  const detailKey = detail ? `${detail.west},${detail.east},${detail.south},${detail.north}` : "";
  const detailSequence = useRef(0);
  useEffect(() => {
    const sequence = ++detailSequence.current;
    if (!source || !detail || !available(source, layer)) {
      renderer.clearSurface("detail");
      dispatch({ type: "detailCleared" });
      return;
    }
    const time = source.times[timeIndex];
    dispatch({ type: "detailStarted" });
    (async () => {
      try {
        const loaded = await frame(source, layer, time, detail, budget);
        if (sequence !== detailSequence.current) return;
        const range = stateRef.current.ranges[layer] ?? loaded.range ?? { minimum: 0, maximum: 1 };
        const outcome = await renderer.showSurface(loaded.field, { palette: LAYERS[layer].palette, range, scale: "linear" }, "detail");
        if (sequence !== detailSequence.current || outcome.status === "superseded") return;
        dispatch(outcome.status === "shown"
          ? { type: "detailShown", factor: loaded.factor }
          : { type: "detailFailed", failure: { code: "unsupported_product", message: outcome.reason } });
      } catch (error) {
        if (sequence === detailSequence.current) dispatch({ type: "detailFailed", failure: failureOf(error) });
      }
    })();
    // detail is read through detailKey, which changes exactly when it does
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderer, frame, budget, source, layer, timeIndex, detailKey]);

  // Playback advances only once the current step is on screen.
  useEffect(() => {
    if (!state.playing || state.frame.phase !== "shown") return;
    const timer = setTimeout(() => dispatch({ type: "tick" }), STEP_MS);
    return () => clearTimeout(timer);
  }, [state.playing, state.frame.phase, timeIndex]);

  // Argo floats inside the viewed area.
  const floatsEnabled = state.floats.enabled;
  useEffect(() => {
    if (!floatsEnabled) {
      renderer.clearMarkers();
      return;
    }
    const query = floatQuery(stateRef.current);
    if (!query) {
      dispatch({ type: "floatsFailed", failure: { code: "observations_unavailable", message: "no observation dataset covers this area" } });
      return;
    }
    const controller = new AbortController();
    dispatch({ type: "floatsStarted" });
    (async () => {
      try {
        const descriptor = await client.observationMarkers(query, controller.signal);
        const markers = decodeMarkers(descriptor, await client.productData(descriptor.data.url, controller.signal));
        if (controller.signal.aborted) return;
        const outcome = renderer.showMarkers(markers);
        dispatch(outcome.status === "shown"
          ? { type: "floatsShown", count: outcome.count }
          : { type: "floatsFailed", failure: { code: "unsupported_product", message: outcome.reason } });
      } catch (error) {
        if (!controller.signal.aborted) dispatch({ type: "floatsFailed", failure: failureOf(error) });
      }
    })();
    return () => controller.abort();
  }, [client, renderer, floatsEnabled]);

  // A picked float's exact profile, every variable its dataset declares.
  const pick = state.profile.pick;
  useEffect(() => {
    if (!pick) return;
    const version = stateRef.current.observations?.find((v) => v.dataset_version_id === pick.datasetVersionId);
    const variables = version?.variables.map((v) => v.name) ?? [];
    const controller = new AbortController();
    (async () => {
      try {
        const descriptor = await client.observationProfile({
          dataset_version_id: pick.datasetVersionId, platform_id: pick.platformId, cycle: pick.cycle, variables,
        }, controller.signal);
        const buffer = await client.productData(descriptor.data.url, controller.signal);
        if (!controller.signal.aborted) dispatch({ type: "profileShown", profile: decodeProfile(descriptor, buffer) });
      } catch (error) {
        if (!controller.signal.aborted) dispatch({ type: "profileFailed", failure: failureOf(error) });
      }
    })();
    return () => controller.abort();
  }, [client, pick]);

  const range = state.ranges[layer];
  const shownFactor = state.detail.phase === "shown" ? state.detail.factor : state.baseFactor;
  const units = displayUnits(state.units[layer] ?? "");
  const time = source?.times[timeIndex];
  const problem = state.renderer.phase !== "ok" ? state.renderer.reason
    : state.catalogue.phase === "failed" ? state.catalogue.message
      : state.frame.phase === "failed" ? state.frame.failure?.message : undefined;

  return (
    <div className="viewer">
      <div className="globe" ref={globeRef} aria-label="3D globe view" />

      <div className="overlay top-left">
        <Paper className="glass" p="md" w={300} shadow="lg">
          <Stack gap="sm">
            <div>
              <Title order={1} size="h4">INCOIS Ocean Viewer</Title>
              <Text size="xs" c="dimmed">
                {source ? `${source.dataset} · sea surface · ${source.times.length} time steps` : "Loading the catalogue…"}
              </Text>
            </div>
            <Text fw={600} size="sm">{LAYERS[layer].title}</Text>
            <Group justify="space-between">
              <Switch
                label="Argo floats"
                checked={state.floats.enabled}
                disabled={!state.observations?.length}
                onChange={() => dispatch({ type: "toggleFloats" })}
              />
              {state.floats.phase === "loading" && <Loader size="xs" />}
              {state.floats.phase === "shown" && <Badge variant="light" color="yellow">{state.floats.count} floats</Badge>}
            </Group>
            {state.floats.phase === "shown" && (
              <Text size="xs" c="dimmed">Select a float to see its temperature and salinity profile.</Text>
            )}
            {state.floats.phase === "failed" && <Text size="xs" c="red">{state.floats.failure?.message}</Text>}
          </Stack>
        </Paper>
      </div>

      {problem && (
        <div className="overlay top">
          <Alert color="red" variant="filled" title="Not shown">{problem}</Alert>
        </div>
      )}

      {state.probe && (
        <div className="overlay top-right">
          <Paper className="glass mono" p="sm" shadow="lg">
            <Text size="xs" c="dimmed">{formatPosition(state.probe.longitude, state.probe.latitude)}</Text>
            <Text fw={600}>
              {state.probe.value.toFixed(2)} {displayUnits(state.probe.units)}
            </Text>
            {state.probe.eastward !== undefined && state.probe.northward !== undefined && (() => {
              const bearing = flowBearing(state.probe.eastward, state.probe.northward);
              return <Text size="xs">toward {bearing.degrees.toFixed(0)}° ({bearing.compass})</Text>;
            })()}
          </Paper>
        </div>
      )}

      {source && (
        <div className="overlay bottom">
          <Paper className="glass" px="md" py="sm" shadow="lg">
            <Group gap="md" wrap="nowrap">
              <ActionIcon
                size="lg" radius="xl" variant="filled"
                aria-label={state.playing ? "Pause" : "Play"}
                disabled={source.times.length < 2}
                onClick={() => dispatch({ type: "togglePlay" })}
              >
                {state.playing ? "❚❚" : "▶"}
              </ActionIcon>
              <Slider
                className="time-slider"
                min={0}
                max={Math.max(0, source.times.length - 1)}
                step={1}
                value={timeIndex}
                onChange={(index) => dispatch({ type: "setTime", index })}
                label={(index) => formatUtc(source.times[index])}
                marks={source.times.map((_, index) => ({ value: index }))}
              />
              <Text className="mono" size="sm" w={150}>{time ? formatUtc(time) : ""}</Text>
              <div style={{ width: 16 }}>{state.frame.phase === "loading" && <Loader size="xs" />}</div>
            </Group>
          </Paper>
        </div>
      )}

      {range && (
        <div className="overlay bottom-right">
          <Paper className="glass" p="sm" w={300} shadow="lg" aria-label={`Colour scale for ${LAYERS[layer].title}`}>
            <Text size="xs" c="dimmed" mb={6}>{LAYERS[layer].title} ({units})</Text>
            <div className="colour-bar" style={{ background: cssGradient(LAYERS[layer].palette) }} />
            <Group justify="space-between" mt={4} className="mono">
              <Text size="xs">{range.minimum.toFixed(1)}</Text>
              <Text size="xs">{((range.minimum + range.maximum) / 2).toFixed(1)}</Text>
              <Text size="xs">{range.maximum.toFixed(1)}</Text>
            </Group>
            <Text size="xs" c="dimmed" mt={6}>{resolutionNote(shownFactor)}</Text>
          </Paper>
        </div>
      )}

      <ProfileDrawer profile={state.profile} onClose={() => dispatch({ type: "profileClosed" })} />
    </div>
  );
}

/** How the cells on screen relate to the model's own cells (S4's record). */
function resolutionNote(factor: number): string {
  return factor <= 1
    ? "Model cells at source resolution"
    : `Zoomed out: each cell is the mean of ${factor}×${factor} model cells; zoom in for source cells`;
}
