// The sea-surface viewer (S7): model layers draped on the globe, a time bar
// that animates the stored time steps, Argo floats with their profiles, and
// an exact readout of the cell under the pointer. All side effects live
// here; the reducer stays pure and the renderer is reached only through its
// facade.
//
// Every layer is requested at the renderer's declared cell budget and
// fitted to it by S4: the whole field as the base layer, and the part in
// view as a finer detail layer. Stepping in time may cross-fade between two
// consecutive real frames; that is a display transition, labelled as one,
// and the readout always reports a real frame.

import {
  Accordion, ActionIcon, Alert, Badge, Button, Group, Loader, NumberInput, Paper,
  SegmentedControl, Select, Slider, Stack, Switch, Text, Title,
} from "@mantine/core";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { ServiceError, type DataClient } from "../api/client";
import { decodeMarkers, decodeProfile } from "../api/observationWire";
import { decodeSlice, decodeVector } from "../api/sliceWire";
import { WireError } from "../api/wire";
import { cssGradient, PALETTES } from "../renderer/colour";
import type {
  Extent, PaletteName, Renderer, RendererFactory, ScaleKind, SurfaceField, SurfaceSlot,
} from "../renderer/contract";
import { robustRange } from "../renderer/surface";
import { detailExtent } from "../state/detail";
import {
  available, describeSource, effectiveRange, floatQuery, initialViewerState, viewerReducer,
  type LayerKind, type Range, type SurfaceSource,
} from "../state/viewer";
import { formatUtc } from "./format";
import { ProfileDrawer } from "./ProfileDrawer";
import { displayUnits, flowBearing, formatPosition } from "./surfaceFormat";

interface Props {
  client: DataClient;
  createRenderer: RendererFactory;
}

const LAYER_TITLES: Record<LayerKind, string> = {
  temperature: "Sea temperature",
  currents: "Current speed",
};

/** A cross-fade between two real frames, then a hold on the real frame. */
const BLEND_MS = 750;
const HOLD_MS = 450;
/** Time on screen per step when cross-fading is off. */
const STEP_MS = 900;
/** Decoded frames kept in memory; a global frame is about 6 MB. */
const CACHED_FRAMES = 16;

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

const extentKey = (e: Extent) => `${e.west},${e.east},${e.south},${e.north}`;

export function Viewer({ client, createRenderer }: Props) {
  const [renderer] = useState<Renderer>(createRenderer);
  const globeRef = useRef<HTMLDivElement>(null);
  const [state, dispatch] = useReducer(viewerReducer, undefined, initialViewerState);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Frames by source, layer, depth, time, extent and budget. Promises are
  // cached so a frame requested twice (shown, then prefetched) is fetched once.
  const frames = useRef(new Map<string, Promise<Frame>>());
  const frame = useCallback((source: SurfaceSource, layer: LayerKind, depth: number, time: string,
                             extent: Extent, budget: number): Promise<Frame> => {
    const key = `${source.versionId}|${layer}|${depth}|${time}|${extentKey(extent)}|${budget}`;
    const cached = frames.current.get(key);
    if (cached) return cached;
    const window = { dataset_version_id: source.versionId, time, depth, ...extent };
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

  const { source, layer, timeIndex, display } = state;
  const depth = source?.depths[state.depthIndex] ?? 0;
  const styleKey = `${display.palette}|${display.scale}|${display.opacity}|${display.customRange?.minimum}|${display.customRange?.maximum}`;

  useEffect(() => {
    if (source) renderer.command({ type: "flyTo", ...source.area });
  }, [renderer, source]);

  // The view budget S4 fits every layer to: this renderer's declared figure.
  const budget = renderer.capabilities.maximumSurfaceCells;

  // What each slot last showed: a change of time on the same place is a
  // step (and may cross-fade); anything else swaps at once.
  const lastShown = useRef<Partial<Record<SurfaceSlot, { place: string; time: string }>>>({});
  const transitionTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  /** Fetch, style and hand one layer to the renderer; resolves its factor. */
  const showLayer = useCallback(async (slot: SurfaceSlot, extent: Extent, isCurrent: () => boolean) => {
    const current = stateRef.current;
    const src = current.source!;
    const lyr = current.layer;
    const dep = src.depths[current.depthIndex];
    const time = src.times[current.timeIndex];
    const loaded = await frame(src, lyr, dep, time, extent, budget);
    if (!isCurrent()) return null;
    // The automatic range is fixed by the first frame of a layer; a user
    // range overrides it for display without replacing it.
    const autoRange = stateRef.current.ranges[lyr] ?? loaded.range ?? { minimum: 0, maximum: 1 };
    const range = current.display.customRange ?? autoRange;
    const place = `${src.versionId}|${lyr}|${dep}|${extentKey(extent)}`;
    const last = lastShown.current[slot];
    const stepping = last !== undefined && last.place === place && last.time !== time;
    const blendMs = current.display.smooth && stepping ? BLEND_MS : 0;
    const outcome = await renderer.showSurface(loaded.field, {
      palette: current.display.palette, range, scale: current.display.scale, opacity: current.display.opacity,
    }, slot, { blendMs });
    if (!isCurrent() || outcome.status === "superseded") return null;
    if (outcome.status === "refused") throw new RefusedLayer(outcome.reason);
    lastShown.current[slot] = { place, time };
    if (slot === "base" && blendMs > 0 && last) {
      dispatch({ type: "transitionStarted", from: last.time, to: time });
      clearTimeout(transitionTimer.current);
      transitionTimer.current = setTimeout(() => dispatch({ type: "transitionEnded" }), blendMs);
    }
    return { loaded, autoRange };
  }, [renderer, frame, budget]);

  // The whole field, fitted to the budget; a newer choice supersedes it.
  const shownSequence = useRef(0);
  useEffect(() => {
    if (!source || !available(source, layer)) return;
    const sequence = ++shownSequence.current;
    dispatch({ type: "frameStarted" });
    (async () => {
      try {
        const shown = await showLayer("base", source.area, () => sequence === shownSequence.current);
        if (!shown) return;
        dispatch({ type: "frameShown", layer, range: shown.autoRange, units: shown.loaded.field.units, factor: shown.loaded.factor });
        // Fetch the next step ahead so playback does not wait on the network.
        const next = source.times[(timeIndex + 1) % source.times.length];
        void frame(source, layer, depth, next, source.area, budget).catch(() => undefined);
      } catch (error) {
        if (sequence !== shownSequence.current) return;
        dispatch({ type: "frameFailed", failure: error instanceof RefusedLayer
          ? { code: "unsupported_product", message: error.message } : failureOf(error) });
      }
    })();
  }, [showLayer, frame, budget, source, layer, timeIndex, depth, styleKey]);

  // The part in view at finer resolution, when the whole-field layer is
  // coarser than the source and most of the field is out of view.
  const detail = useMemo(
    () => (source ? detailExtent(source.area, state.view, state.baseFactor) : null),
    [source, state.view, state.baseFactor]);
  const detailKey = detail ? extentKey(detail) : "";
  const detailSequence = useRef(0);
  useEffect(() => {
    const sequence = ++detailSequence.current;
    if (!source || !detail || !available(source, layer)) {
      renderer.clearSurface("detail");
      delete lastShown.current.detail;
      dispatch({ type: "detailCleared" });
      return;
    }
    dispatch({ type: "detailStarted" });
    (async () => {
      try {
        const shown = await showLayer("detail", detail, () => sequence === detailSequence.current);
        if (shown) dispatch({ type: "detailShown", factor: shown.loaded.factor });
      } catch (error) {
        if (sequence !== detailSequence.current) return;
        dispatch({ type: "detailFailed", failure: error instanceof RefusedLayer
          ? { code: "unsupported_product", message: error.message } : failureOf(error) });
      }
    })();
    // detail is read through detailKey, which changes exactly when it does
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderer, showLayer, source, layer, timeIndex, depth, styleKey, detailKey]);

  // Playback advances only once the current step is on screen.
  useEffect(() => {
    if (!state.playing || state.frame.phase !== "shown") return;
    const timer = setTimeout(() => dispatch({ type: "tick" }), display.smooth ? BLEND_MS + HOLD_MS : STEP_MS);
    return () => clearTimeout(timer);
  }, [state.playing, state.frame.phase, timeIndex, display.smooth]);

  // Argo floats over their own dataset's extent.
  const floatsEnabled = state.floats.enabled;
  useEffect(() => {
    if (!floatsEnabled) {
      renderer.clearMarkers();
      return;
    }
    const query = floatQuery(stateRef.current);
    if (!query) {
      dispatch({ type: "floatsFailed", failure: { code: "observations_unavailable", message: "no observation dataset is stored" } });
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

  const range = effectiveRange(state);
  const shownFactor = state.detail.phase === "shown" ? state.detail.factor : state.baseFactor;
  const units = displayUnits(state.units[layer] ?? "");
  const time = source?.times[timeIndex];
  const problem = state.renderer.phase !== "ok" ? state.renderer.reason
    : state.catalogue.phase === "failed" ? state.catalogue.message
      : state.frame.phase === "failed" ? state.frame.failure?.message : undefined;
  const depthLabel = depth === 0 ? "surface" : `${Math.round(depth)} m`;

  return (
    <div className="viewer">
      <div className="globe" ref={globeRef} aria-label="3D globe view" />

      <div className="overlay top-left">
        <Paper className="glass" p="md" w={320} shadow="lg">
          <Stack gap="sm">
            <div>
              <Title order={1} size="h4">INCOIS Ocean Viewer</Title>
              <Text size="xs" c="dimmed">
                {source ? `${LAYER_TITLES[layer]} · ${depthLabel[0].toUpperCase()}${depthLabel.slice(1)} · HYCOM model` : "Loading…"}
              </Text>
            </div>
            {state.sources.length > 1 && (
              <Select
                label="Dataset" size="xs" allowDeselect={false}
                value={source?.versionId ?? null}
                onChange={(versionId) => versionId && dispatch({ type: "selectSource", versionId })}
                data={state.sources.map((s) => ({ value: s.versionId, label: describeSource(s) }))}
              />
            )}
            {source && source.depths.length > 1 && (
              <Select
                label="Depth" size="xs" allowDeselect={false}
                value={String(state.depthIndex)}
                onChange={(index) => index !== null && dispatch({ type: "setDepth", index: Number(index) })}
                data={source.depths.map((d, index) => ({ value: String(index), label: d === 0 ? "Surface (0 m)" : `${Math.round(d)} m` }))}
              />
            )}
            <Accordion variant="contained" chevronPosition="right" styles={{ content: { padding: "8px 10px 12px" }, control: { padding: "4px 10px" } }}>
              <Accordion.Item value="display">
                <Accordion.Control><Text size="sm">Display</Text></Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="xs">
            <Group grow gap="xs">
              <Select
                label="Palette" size="xs" allowDeselect={false}
                value={display.palette}
                onChange={(palette) => palette && dispatch({ type: "setDisplay", patch: { palette: palette as PaletteName } })}
                data={PALETTES.map((p) => ({ value: p, label: p[0].toUpperCase() + p.slice(1) }))}
              />
              <div>
                <Text size="xs" fw={500} mb={4}>Scale</Text>
                <SegmentedControl
                  size="xs" fullWidth value={display.scale}
                  onChange={(scale) => dispatch({ type: "setDisplay", patch: { scale: scale as ScaleKind } })}
                  data={[{ value: "linear", label: "Linear" }, { value: "log", label: "Log" }]}
                />
              </div>
            </Group>
            <Group gap="xs" align="flex-end" wrap="nowrap">
              <NumberInput
                label={`Min (${units})`} size="xs" decimalScale={2} step={0.5}
                value={range?.minimum ?? ""}
                onChange={(v) => typeof v === "number" && range && dispatch({ type: "setDisplay", patch: { customRange: { minimum: v, maximum: range.maximum } } })}
              />
              <NumberInput
                label={`Max (${units})`} size="xs" decimalScale={2} step={0.5}
                value={range?.maximum ?? ""}
                onChange={(v) => typeof v === "number" && range && dispatch({ type: "setDisplay", patch: { customRange: { minimum: range.minimum, maximum: v } } })}
              />
              <Button size="xs" variant="light" disabled={!display.customRange}
                onClick={() => dispatch({ type: "setDisplay", patch: { customRange: null } })}>
                Auto
              </Button>
            </Group>
            <div>
              <Text size="xs" fw={500}>Opacity</Text>
              <Slider
                size="sm" min={0.2} max={1} step={0.05} value={display.opacity}
                label={(v) => `${Math.round(v * 100)}%`}
                onChange={(opacity) => dispatch({ type: "setDisplay", patch: { opacity } })}
              />
            </div>
            <Switch
              label="Smooth playback" size="xs"
              checked={display.smooth}
              onChange={() => dispatch({ type: "setDisplay", patch: { smooth: !display.smooth } })}
            />
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
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
              <Text size="xs" c="dimmed">Click a float to see its profile.</Text>
            )}
            {state.floats.phase === "failed" && <Text size="xs" c="red">{state.floats.failure?.message}</Text>}
          </Stack>
        </Paper>
      </div>

      {problem && (
        <div className="overlay top">
          <Alert color="red" variant="light" withCloseButton={false}>{problem}</Alert>
        </div>
      )}

      {state.probe && (
        <div className="overlay top-right">
          <Paper className="glass mono" p="sm" shadow="lg">
            <Text size="xs" c="dimmed">{formatPosition(state.probe.longitude, state.probe.latitude)} · {depthLabel}</Text>
            <Text fw={600}>
              {state.probe.value.toFixed(2)} {displayUnits(state.probe.units)}
            </Text>
            {state.probe.eastward !== undefined && state.probe.northward !== undefined && (() => {
              const bearing = flowBearing(state.probe.eastward, state.probe.northward);
              return <Text size="xs">toward {bearing.degrees.toFixed(0)}° ({bearing.compass})</Text>;
            })()}
            {time && <Text size="xs" c="dimmed">{formatUtc(time)}</Text>}
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
                marks={source.times.length <= 40 ? source.times.map((_, index) => ({ value: index })) : undefined}
              />
              <Text className="mono" size="sm" w={200} ta="right">
                {state.transition
                  ? `${formatUtc(state.transition.from).slice(5, 16)} → ${formatUtc(state.transition.to).slice(5)}`
                  : time ? formatUtc(time) : ""}
              </Text>
              <div style={{ width: 16 }}>{state.frame.phase === "loading" && <Loader size="xs" />}</div>
            </Group>
          </Paper>
        </div>
      )}

      {range && (
        <div className="overlay bottom-right">
          <Paper className="glass" p="sm" w={300} shadow="lg" aria-label={`Colour scale for ${LAYER_TITLES[layer]}`}>
            <Text size="xs" c="dimmed" mb={6}>
              {LAYER_TITLES[layer]} ({units}){display.scale === "log" ? " · log" : ""}
            </Text>
            <div className="colour-bar" style={{ background: cssGradient(display.palette) }} />
            <Group justify="space-between" mt={4} className="mono">
              <Text size="xs">{range.minimum.toFixed(1)}</Text>
              <Text size="xs">
                {(display.scale === "log" && range.minimum > 0
                  ? Math.sqrt(range.minimum * range.maximum)
                  : (range.minimum + range.maximum) / 2).toFixed(1)}
              </Text>
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

/** The renderer declined a layer (for example a log scale over values <= 0). */
class RefusedLayer extends Error {}

/** How the cells on screen relate to the model's own cells (S4's record). */
function resolutionNote(factor: number): string {
  return factor <= 1
    ? "Full model resolution"
    : `Averaged ${factor}×${factor} · zoom in for full detail`;
}
