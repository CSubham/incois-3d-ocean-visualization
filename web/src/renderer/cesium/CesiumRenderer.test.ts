// Contract tests for the CesiumJS adapter against an in-memory stand-in for
// the engine: what is drawn, refused, disposed and reported, without a GPU.

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MarkerSet } from "../../api/observationWire";
import type { PointFieldArrays, ProductDescriptor } from "../../api/wire";
import type { DisplayState, RendererEvent } from "../contract";

const engine = vi.hoisted(() => {
  const state = {
    viewers: [] as any[],
    handlers: [] as any[],
    failMount: false,
    pick: null as any,
  };
  class Color {
    constructor(public red = 0, public green = 0, public blue = 0, public alpha = 1) {}
    withAlpha(alpha: number) { return new Color(this.red, this.green, this.blue, alpha); }
    static fromCssColorString() { return new Color(); }
    static WHITE = new Color(1, 1, 1, 1);
    static GRAY = new Color(0.5, 0.5, 0.5, 1);
    static TRANSPARENT = new Color(0, 0, 0, 0);
  }
  class PointPrimitiveCollection {
    points: any[] = [];
    add(options: any) { const point = { ...options }; this.points.push(point); return point; }
  }
  class Canvas {
    style: Record<string, string> = {};
    listeners: Record<string, ((event: any) => void)[]> = {};
    addEventListener(type: string, listener: (event: any) => void) { (this.listeners[type] ??= []).push(listener); }
    dispatch(type: string) { for (const l of this.listeners[type] ?? []) l({ preventDefault() {} }); }
  }
  class Viewer {
    destroyed = false;
    renderErrorListeners: ((scene: unknown, error: unknown) => void)[] = [];
    scene = {
      primitives: { items: [] as any[], add(p: any) { this.items.push(p); return p; }, remove(p: any) { this.items = this.items.filter((i) => i !== p); } },
      globe: { translucency: { enabled: false, frontFaceAlpha: 1, rectangle: null as any }, undergroundColor: null as any },
      screenSpaceCameraController: { enableCollisionDetection: true },
      renderError: { addEventListener: (l: any) => this.renderErrorListeners.push(l) },
      canvas: new Canvas(),
      requestRender() {},
      pick: () => state.pick,
    };
    imageryLayers = { addImageryProvider() {} };
    camera = { setView() {}, flyToBoundingSphere() {} };
    entities = { items: [] as any[], add(e: any) { this.items.push(e); return e; }, remove(e: any) { this.items = this.items.filter((i) => i !== e); } };
    constructor() {
      if (state.failMount) throw new Error("no WebGL");
      state.viewers.push(this);
    }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  }
  class ScreenSpaceEventHandler {
    actions = new Map<string, (event: any) => void>();
    destroyed = false;
    constructor() { state.handlers.push(this); }
    setInputAction(action: (event: any) => void, type: string) { this.actions.set(type, action); }
    destroy() { this.destroyed = true; }
  }
  return {
    state,
    module: {
      Viewer, Color, PointPrimitiveCollection, ScreenSpaceEventHandler,
      PointPrimitive: class {},
      ScreenSpaceEventType: { MOUSE_MOVE: "move", LEFT_CLICK: "click" },
      Cartesian3: {
        fromDegrees: (longitude: number, latitude: number, height = 0) => ({ longitude, latitude, height }),
        fromDegreesArrayHeights: (values: number[]) => values,
      },
      BoundingSphere: { fromPoints: () => ({ radius: 1 }) },
      HeadingPitchRange: class { constructor(public heading: number, public pitch: number, public range: number) {} },
      Rectangle: { fromDegrees: (...bounds: number[]) => bounds },
      ImageryLayer: { fromProviderAsync: () => ({}) },
      TileMapServiceImageryProvider: { fromUrl: () => Promise.resolve({}) },
      GridImageryProvider: class { constructor(public options: unknown) {} },
      buildModuleUrl: (path: string) => path,
    },
  };
});

vi.mock("cesium", () => engine.module);
vi.mock("cesium/Build/Cesium/Widgets/widgets.css", () => ({}));

const { CesiumRenderer } = await import("./CesiumRenderer");

const display: DisplayState = {
  palette: "viridis", range: { minimum: 0, maximum: 30 }, scale: "linear",
  opacity: 1, verticalExaggeration: 100,
};

function field(crs = "EPSG:4326", depthUnits: string | null = "m", count = 3): { descriptor: ProductDescriptor; arrays: PointFieldArrays } {
  const descriptor = {
    point_count: count,
    product: {
      spatial_reference: { crs, vertical_positive: "down" },
      coordinates: { units: { depth: depthUnits } },
    },
  } as unknown as ProductDescriptor;
  const arrays: PointFieldArrays = {
    longitude: new Float64Array([80, 81, 82]),
    latitude: new Float64Array([10, 11, 12]),
    depth: new Float64Array([0, 500, 1000]),
    // A float64 value float32 cannot hold, a masked cell, and a plain one.
    values: new Float64Array([20.123456789012345, 25, 5]),
    missingValueMask: new Uint8Array([0, 1, 0]),
  };
  return { descriptor, arrays };
}

const markers: MarkerSet = {
  datasetVersionId: "v-argo", crs: "EPSG:4326", verticalKind: "pressure", verticalUnits: "decibar",
  longitude: new Float32Array([73.5]), latitude: new Float32Array([8.5]),
  verticalMinimum: new Float32Array([2]), verticalMaximum: new Float32Array([10]),
  platformIds: ["7902250"], cycles: ["12"], observedAt: ["2026-09-28T00:00:00"],
};

function mounted() {
  const renderer = new CesiumRenderer(1000);
  const events: RendererEvent[] = [];
  renderer.onEvent((event) => events.push(event));
  renderer.mount({} as HTMLElement);
  const viewer = engine.state.viewers.at(-1);
  const handler = engine.state.handlers.at(-1);
  return { renderer, events, viewer, handler };
}

beforeEach(() => {
  engine.state.viewers.length = 0;
  engine.state.handlers.length = 0;
  engine.state.failMount = false;
  engine.state.pick = null;
});

describe("CesiumRenderer", () => {
  it("draws only valid cells and reports how many were left out", () => {
    const { renderer, viewer } = mounted();
    const { descriptor, arrays } = field();

    expect(renderer.showPointField(descriptor, arrays)).toEqual({ status: "shown", shownPoints: 2, hiddenMissingPoints: 1 });
    const [layer] = viewer.scene.primitives.items;
    expect(layer.points.map((p: any) => p.position.longitude)).toEqual([80, 82]);
  });

  it("places depth below the ellipsoid, scaled only by exaggeration", () => {
    const { renderer, viewer } = mounted();
    renderer.applyDisplay(display);
    const { descriptor, arrays } = field();
    renderer.showPointField(descriptor, arrays);
    const [layer] = viewer.scene.primitives.items;

    expect(layer.points[1].position.height).toBe(-1000 * 100);
    renderer.applyDisplay({ ...display, verticalExaggeration: 1 });
    expect(layer.points[1].position.height).toBe(-1000);
  });

  it("refuses an unsupported CRS and leaves the previous field untouched", () => {
    const { renderer, viewer } = mounted();
    const first = field();
    renderer.showPointField(first.descriptor, first.arrays);
    const before = [...viewer.scene.primitives.items];

    const outcome = renderer.showPointField(field("EPSG:3857").descriptor, first.arrays);
    expect(outcome).toMatchObject({ status: "refused" });
    expect(viewer.scene.primitives.items).toEqual(before);
  });

  it("asks for a lower density instead of drawing an oversized field", () => {
    const { renderer, viewer } = mounted();
    const big = field(undefined, undefined, 5000);

    expect(renderer.showPointField(big.descriptor, big.arrays)).toMatchObject({ status: "too-large", retryWithPoints: 1000 });
    expect(viewer.scene.primitives.items).toHaveLength(0);
  });

  it("reports hovered values at full precision, not narrowed to float32", () => {
    const { renderer, events, viewer, handler } = mounted();
    const { descriptor, arrays } = field();
    renderer.showPointField(descriptor, arrays);
    engine.state.pick = { collection: viewer.scene.primitives.items[0], id: 0 };

    handler.actions.get("move")({ endPosition: {} });
    expect(events.at(-1)).toEqual({
      type: "hover",
      sample: { longitude: 80, latitude: 10, depth: 0, value: 20.123456789012345 },
    });
  });

  it("refuses a log scale it cannot apply and changes nothing", () => {
    const { renderer } = mounted();
    expect(renderer.applyDisplay({ ...display, scale: "log", range: { minimum: 0, maximum: 1 } }))
      .toMatchObject({ status: "refused" });
  });

  it("emits the exact identity of a clicked marker", () => {
    const { renderer, events, viewer, handler } = mounted();
    expect(renderer.showMarkers(markers)).toEqual({ status: "shown", count: 1 });
    engine.state.pick = { collection: viewer.scene.primitives.items[0], id: { marker: 0 } };

    handler.actions.get("click")({ position: {} });
    expect(events.at(-1)).toEqual({
      type: "pick",
      marker: { datasetVersionId: "v-argo", platformId: "7902250", cycle: "12",
        longitude: Math.fround(73.5), latitude: Math.fround(8.5), observedAt: "2026-09-28T00:00:00" },
    });
  });

  it("refuses markers in a reference it cannot place", () => {
    const { renderer, viewer } = mounted();
    expect(renderer.showMarkers({ ...markers, crs: "EPSG:32643" })).toMatchObject({ status: "refused" });
    expect(viewer.scene.primitives.items).toHaveLength(0);
  });

  it("reports a lost context and a render failure as distinct events", () => {
    const { events, viewer } = mounted();
    viewer.scene.canvas.dispatch("webglcontextlost");
    viewer.renderErrorListeners[0](viewer.scene, new Error("shader"));
    expect(events.map((e) => e.type)).toEqual(["contextLost", "renderFailed"]);
  });

  it("reports a browser that cannot create the globe as unsupported", () => {
    engine.state.failMount = true;
    const { events } = mounted();
    expect(events).toEqual([{ type: "unsupported", reason: expect.stringContaining("WebGL") }]);
  });

  it("releases every layer and the viewer on dispose", () => {
    const { renderer, viewer, handler } = mounted();
    const { descriptor, arrays } = field();
    renderer.showPointField(descriptor, arrays);
    renderer.showMarkers(markers);

    renderer.dispose();
    expect(viewer.scene.primitives.items).toHaveLength(0);
    expect(handler.destroyed).toBe(true);
    expect(viewer.destroyed).toBe(true);
  });
});
