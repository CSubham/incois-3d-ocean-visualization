// CesiumJS: the renderer-facade implementation (Decision Record D12).
//
// The field is shown on the Earth: an offline Natural Earth II globe with a
// lat/lon grid, translucent only over the selected region so the water
// column beneath the sea surface stays visible. Each point is placed
// geodetically at its own longitude and latitude, with height equal to the
// exaggerated depth below the ellipsoid; a flat local frame would drift tens
// of kilometres off the curved surface across a regional selection.
// Exaggeration and colour are display state only: physical values are kept
// untouched and positions are recomputed from them.

import {
  BoundingSphere, buildModuleUrl, Cartesian3, Color, GridImageryProvider,
  HeadingPitchRange, ImageryLayer, PointPrimitive, PointPrimitiveCollection,
  Rectangle, ScreenSpaceEventHandler, ScreenSpaceEventType,
  TileMapServiceImageryProvider, Viewer, type Cartesian2, type Entity,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

import type { PointFieldArrays, ProductDescriptor } from "../../api/wire";
import { logScaleProblem, normalise, paletteColour } from "../colour";
import type {
  DisplayState, PointSample, Renderer, RendererCapabilities, RendererCommand,
  RendererEvent,
} from "../contract";
import { sceneFrame, TransformError } from "../transform";

const POINT_PIXELS = 4;
const REGION_OUTLINE = Color.fromCssColorString("#9fd3ea").withAlpha(0.9);

interface Layer {
  collection: PointPrimitiveCollection;
  points: PointPrimitive[];
  longitude: Float64Array;
  latitude: Float64Array;
  /** Metres above the ellipsoid before exaggeration; negative below it. */
  height: Float64Array;
  depth: Float64Array;
  values: Float32Array;
  bounds: { west: number; east: number; south: number; north: number };
  deepest: number;
  outline: Entity[];
  coloured: boolean;
}

export class CesiumRenderer implements Renderer {
  readonly capabilities: RendererCapabilities;
  private readonly listeners = new Set<(event: RendererEvent) => void>();
  private viewer?: Viewer;
  private handler?: ScreenSpaceEventHandler;
  private layer?: Layer;
  private display?: DisplayState;
  private hovered: number | null = null;

  constructor(maximumPoints: number) {
    this.capabilities = { engine: "CesiumJS on WebGL2", maximumPoints };
  }

  mount(container: HTMLElement): void {
    try {
      this.viewer = new Viewer(container, {
        baseLayer: ImageryLayer.fromProviderAsync(TileMapServiceImageryProvider.fromUrl(
          buildModuleUrl("Assets/Textures/NaturalEarthII"))),
        baseLayerPicker: false, geocoder: false, homeButton: false,
        sceneModePicker: false, navigationHelpButton: false, animation: false,
        timeline: false, fullscreenButton: false, infoBox: false,
        selectionIndicator: false, showRenderLoopErrors: false,
        requestRenderMode: true, maximumRenderTimeChange: Infinity,
      });
    } catch {
      this.emit({ type: "unsupported", reason: "this browser cannot create the WebGL context the globe requires" });
      return;
    }
    const { scene } = this.viewer;
    this.viewer.imageryLayers.addImageryProvider(new GridImageryProvider({
      color: Color.WHITE.withAlpha(0.12), glowColor: Color.TRANSPARENT,
      backgroundColor: Color.TRANSPARENT, cells: 1,
    }));
    scene.globe.undergroundColor = Color.fromCssColorString("#07131f");
    scene.globe.translucency.frontFaceAlpha = 0.35;
    scene.screenSpaceCameraController.enableCollisionDetection = false;
    scene.renderError.addEventListener((_scene, error) => {
      this.emit({ type: "error", reason: `the globe stopped rendering: ${String(error)}` });
    });
    scene.canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      this.emit({ type: "error", reason: "the graphics context was lost; reload to restore the view" });
    });
    this.handler = new ScreenSpaceEventHandler(scene.canvas);
    this.handler.setInputAction((movement: { endPosition: Cartesian2 }) => this.hover(movement.endPosition),
      ScreenSpaceEventType.MOUSE_MOVE);
    // Start over the northern Indian Ocean.
    this.viewer.camera.setView({ destination: Cartesian3.fromDegrees(78, 5, 9_000_000) });
  }

  showPointField(descriptor: ProductDescriptor, arrays: PointFieldArrays): void {
    const viewer = this.viewer;
    if (!viewer) return;
    if (descriptor.point_count > this.capabilities.maximumPoints) {
      this.emit({
        type: "resource",
        reason: `${descriptor.point_count} points exceed this view's limit of ${this.capabilities.maximumPoints}`,
        retryWithPoints: this.capabilities.maximumPoints,
      });
      return;
    }
    const product = descriptor.product;
    const bounds = extent(arrays.longitude, arrays.latitude);
    let frame;
    try {
      frame = sceneFrame(product.spatial_reference.crs, product.coordinates.units.depth,
        product.spatial_reference.vertical_positive, bounds);
    } catch (error) {
      if (error instanceof TransformError) {
        this.emit({ type: "unsupported", reason: error.message });
        return;
      }
      throw error;
    }

    this.clear();
    const count = arrays.values.length;
    const longitude = new Float64Array(count), latitude = new Float64Array(count);
    const height = new Float64Array(count), depth = new Float64Array(count);
    const values = new Float32Array(count);
    const heightPerDepthUnit = -frame.depthSign * frame.depthToKm * 1000;
    let shown = 0;
    let deepest = 0;
    for (let i = 0; i < count; i++) {
      const value = arrays.values[i];
      if (arrays.missingValueMask[i] || !Number.isFinite(value)) continue;
      longitude[shown] = arrays.longitude[i];
      latitude[shown] = arrays.latitude[i];
      depth[shown] = arrays.depth[i];
      height[shown] = arrays.depth[i] * heightPerDepthUnit;
      values[shown] = value;
      deepest = Math.min(deepest, height[shown]);
      shown++;
    }

    const collection = viewer.scene.primitives.add(new PointPrimitiveCollection()) as PointPrimitiveCollection;
    const exaggeration = this.display?.verticalExaggeration ?? 1;
    const points: PointPrimitive[] = new Array(shown);
    for (let i = 0; i < shown; i++) {
      points[i] = collection.add({
        position: Cartesian3.fromDegrees(longitude[i], latitude[i], height[i] * exaggeration),
        pixelSize: POINT_PIXELS,
        color: Color.GRAY,
        id: i,
      });
    }
    this.layer = {
      collection, points, bounds, deepest, coloured: false, outline: [],
      longitude: longitude.subarray(0, shown), latitude: latitude.subarray(0, shown),
      height: height.subarray(0, shown), depth: depth.subarray(0, shown),
      values: values.subarray(0, shown),
    };
    viewer.scene.globe.translucency.rectangle = Rectangle.fromDegrees(
      bounds.west, bounds.south, bounds.east, bounds.north);
    viewer.scene.globe.translucency.enabled = true;
    this.drawOutline(exaggeration);
    if (this.display) this.applyDisplay(this.display);
    this.flyToRegion();
    this.emit({ type: "ready", shownPoints: shown, hiddenMissingPoints: count - shown });
  }

  clear(): void {
    const viewer = this.viewer;
    const layer = this.layer;
    if (!viewer || !layer) return;
    viewer.scene.primitives.remove(layer.collection);   // destroys its GPU resources
    for (const entity of layer.outline) viewer.entities.remove(entity);
    viewer.scene.globe.translucency.enabled = false;
    this.layer = undefined;
    this.setHovered(null);
    viewer.scene.requestRender();
  }

  applyDisplay(display: DisplayState): void {
    const previous = this.display;
    this.display = display;
    const layer = this.layer;
    if (!layer || !this.viewer) return;

    if (!previous || previous.verticalExaggeration !== display.verticalExaggeration) {
      const e = display.verticalExaggeration;
      for (let i = 0; i < layer.points.length; i++) {
        layer.points[i].position = Cartesian3.fromDegrees(layer.longitude[i], layer.latitude[i], layer.height[i] * e);
      }
      this.drawOutline(e);
    }

    const recolour = !layer.coloured || !previous || previous.palette !== display.palette ||
      previous.scale !== display.scale || previous.opacity !== display.opacity ||
      previous.range.minimum !== display.range.minimum || previous.range.maximum !== display.range.maximum;
    if (recolour) {
      const { minimum, maximum } = display.range;
      const problem = display.scale === "log" ? logScaleProblem(minimum, maximum) : null;
      if (problem) {
        this.emit({ type: "error", reason: problem });
      } else {
        for (let i = 0; i < layer.points.length; i++) {
          const [r, g, b] = paletteColour(display.palette, normalise(layer.values[i], minimum, maximum, display.scale));
          layer.points[i].color = new Color(r, g, b, display.opacity);
        }
        layer.coloured = true;
      }
    }
    this.viewer.scene.requestRender();
  }

  command(command: RendererCommand): void {
    if (command.type === "resetCamera") this.flyToRegion();
  }

  onEvent(listener: (event: RendererEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose(): void {
    this.handler?.destroy();
    if (this.viewer && !this.viewer.isDestroyed()) this.viewer.destroy();
    this.viewer = undefined;
    this.layer = undefined;
    this.listeners.clear();
  }

  // The region at the sea surface and at its deepest shown level, joined at
  // the corners, so depth and extent read at a glance.
  private drawOutline(exaggeration: number): void {
    const viewer = this.viewer;
    const layer = this.layer;
    if (!viewer || !layer) return;
    for (const entity of layer.outline) viewer.entities.remove(entity);
    const { west, east, south, north } = layer.bounds;
    const bottom = layer.deepest * exaggeration;
    const rectangle = Rectangle.fromDegrees(west, south, east, north);
    const corners: [number, number][] = [[west, south], [east, south], [east, north], [west, north]];
    layer.outline = [
      viewer.entities.add({ rectangle: { coordinates: rectangle, height: 0, fill: false, outline: true, outlineColor: REGION_OUTLINE } }),
      viewer.entities.add({ rectangle: { coordinates: rectangle, height: bottom, fill: false, outline: true, outlineColor: REGION_OUTLINE.withAlpha(0.5) } }),
      ...corners.map(([lon, lat]) => viewer.entities.add({
        polyline: { positions: Cartesian3.fromDegreesArrayHeights([lon, lat, 0, lon, lat, bottom]), width: 1, material: REGION_OUTLINE.withAlpha(0.5) },
      })),
    ];
  }

  private flyToRegion(): void {
    const viewer = this.viewer;
    const layer = this.layer;
    if (!viewer || !layer) return;
    const { west, east, south, north } = layer.bounds;
    const sphere = BoundingSphere.fromPoints([
      Cartesian3.fromDegrees(west, south), Cartesian3.fromDegrees(east, north),
      Cartesian3.fromDegrees(west, north), Cartesian3.fromDegrees(east, south),
    ]);
    viewer.camera.flyToBoundingSphere(sphere, {
      offset: new HeadingPitchRange(0, -0.62, sphere.radius * 2.6),
      duration: 1.2,
    });
  }

  private hover(position: Cartesian2): void {
    const viewer = this.viewer;
    const layer = this.layer;
    if (!viewer || !layer) return;
    const picked = viewer.scene.pick(position);
    const index = picked?.collection === layer.collection && typeof picked.id === "number" ? picked.id : null;
    this.setHovered(index);
  }

  private setHovered(index: number | null): void {
    if (index === this.hovered) return;
    this.hovered = index;
    const layer = this.layer;
    let sample: PointSample | null = null;
    if (index !== null && layer) {
      sample = { longitude: layer.longitude[index], latitude: layer.latitude[index], depth: layer.depth[index], value: layer.values[index] };
    }
    this.emit({ type: "hover", sample });
  }

  private emit(event: RendererEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}

function extent(longitude: ArrayLike<number>, latitude: ArrayLike<number>) {
  let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
  for (let i = 0; i < longitude.length; i++) {
    west = Math.min(west, longitude[i]); east = Math.max(east, longitude[i]);
    south = Math.min(south, latitude[i]); north = Math.max(north, latitude[i]);
  }
  return { west, east, south, north };
}
