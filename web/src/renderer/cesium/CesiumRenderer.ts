// CesiumJS: the renderer-facade implementation (Decision Record D12).
//
// The field is shown on the Earth: an offline Natural Earth II globe with a
// lat/lon grid, translucent only over the selected region so the water
// column beneath the sea surface stays visible. Each point is placed
// geodetically at its own longitude and latitude, with height equal to the
// exaggerated depth below the ellipsoid; a flat local frame would drift tens
// of kilometres off the curved surface across a regional selection.
// Exaggeration and colour are display state only: physical values are read
// from the decoded product itself and positions are recomputed from them.
//
// Every product is validated before the current layer is touched, so a
// refusal leaves the previous field displayed exactly as S7 still describes it.

import {
  BillboardCollection, BoundingSphere, buildModuleUrl, Cartesian3, Cartographic,
  Color, Ellipsoid, GridImageryProvider, HeadingPitchRange, ImageryLayer,
  Math as CesiumMath, PointPrimitive, PointPrimitiveCollection, Rectangle,
  ScreenSpaceEventHandler, ScreenSpaceEventType, SingleTileImageryProvider,
  TileMapServiceImageryProvider, Viewer, type Cartesian2, type Entity,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

import type { MarkerSet } from "../../api/observationWire";
import type { NumericArray, PointFieldArrays, ProductDescriptor } from "../../api/wire";
import { logScaleProblem, normalise, paletteColour } from "../colour";
import type {
  ArrowSet, DisplayOutcome, DisplayState, Extent, FieldOutcome, MarkerOutcome, PointSample,
  Renderer, RendererCapabilities, RendererCommand, RendererEvent, SurfaceField,
  SurfaceOutcome, SurfaceSample, SurfaceSlot, SurfaceStyle,
} from "../contract";
import { markerPick } from "../markers";
import { cellAt, gridGeometry, rasterise, SurfaceError, type GridGeometry } from "../surface";
import { isGeographicCrs, sceneFrame, TransformError } from "../transform";

const POINT_PIXELS = 4;
const MARKER_PIXELS = 11;
const MARKER_FILL = Color.fromCssColorString("#ffcf5a");
const REGION_OUTLINE = Color.fromCssColorString("#9fd3ea").withAlpha(0.9);
const SURFACE_ALPHA = 0.92;
/** Arrows sit just above the sea surface so the globe never hides them. */
const ARROW_HEIGHT_M = 2_000;
const ARROW_PIXELS = 22;

interface Surface {
  layer: ImageryLayer;
  geometry: GridGeometry;
  field: SurfaceField;
}

interface Layer {
  collection: PointPrimitiveCollection;
  points: PointPrimitive[];
  /** The decoded product arrays; values are read from here at full precision. */
  source: PointFieldArrays;
  /** Source index of each drawn point. */
  index: Uint32Array;
  /** Metres above the ellipsoid before exaggeration; negative below it. */
  height: Float64Array;
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
  private markers?: { collection: PointPrimitiveCollection; set: MarkerSet };
  private readonly surfaces: Partial<Record<SurfaceSlot, Surface>> = {};
  /** Increments per hand-over; an image finishing after a newer one is dropped. */
  private readonly surfaceGeneration: Record<SurfaceSlot, number> = { base: 0, detail: 0 };
  private probedCell: number | null = null;
  private arrows?: BillboardCollection;

  constructor(maximumPoints: number, maximumSurfaceCells: number) {
    this.capabilities = {
      engine: "CesiumJS on WebGL2", maximumPoints, maximumSurfaceCells,
      maximumTextureSide: textureSideLimit(),
    };
  }

  mount(container: HTMLElement): void {
    try {
      this.viewer = new Viewer(container, {
        baseLayer: ImageryLayer.fromProviderAsync(TileMapServiceImageryProvider.fromUrl(
          buildModuleUrl("Assets/Textures/NaturalEarthII")), { brightness: 0.8 }),
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
    scene.renderError.addEventListener((_scene: unknown, error: unknown) => {
      this.emit({ type: "renderFailed", reason: `the globe stopped rendering: ${String(error)}` });
    });
    // CesiumJS does not rebuild its GPU resources after a context loss, so the
    // loss is reported as permanent rather than as a recoverable error.
    scene.canvas.addEventListener("webglcontextlost", (event: Event) => {
      event.preventDefault();
      this.emit({ type: "contextLost", reason: "the graphics context was lost; reload the page to restore the view" });
    });
    this.handler = new ScreenSpaceEventHandler(scene.canvas);
    this.handler.setInputAction((movement: { endPosition: Cartesian2 }) => this.hover(movement.endPosition),
      ScreenSpaceEventType.MOUSE_MOVE);
    this.handler.setInputAction((click: { position: Cartesian2 }) => this.select(click.position),
      ScreenSpaceEventType.LEFT_CLICK);
    // Start over the northern Indian Ocean.
    this.viewer.camera.setView({ destination: Cartesian3.fromDegrees(78, 5, 9_000_000) });
    this.viewer.camera.moveEnd.addEventListener(() => this.emit({ type: "view", extent: this.viewExtent() }));
  }

  showPointField(descriptor: ProductDescriptor, arrays: PointFieldArrays): FieldOutcome {
    const viewer = this.viewer;
    if (!viewer) return { status: "refused", reason: "the 3D view is not available" };
    if (descriptor.point_count > this.capabilities.maximumPoints) {
      return {
        status: "too-large",
        reason: `${descriptor.point_count} points exceed this view's limit of ${this.capabilities.maximumPoints}`,
        retryWithPoints: this.capabilities.maximumPoints,
      };
    }
    const product = descriptor.product;
    const bounds = extent(arrays.longitude, arrays.latitude);
    let frame;
    try {
      frame = sceneFrame(product.spatial_reference.crs, product.coordinates.units.depth,
        product.spatial_reference.vertical_positive, bounds);
    } catch (error) {
      if (error instanceof TransformError) return { status: "refused", reason: error.message };
      throw error;
    }

    // Valid from here on: only now is the previous field replaced.
    this.clear();
    const count = arrays.values.length;
    const index = new Uint32Array(count);
    const height = new Float64Array(count);
    const heightPerDepthUnit = -frame.depthSign * frame.depthToKm * 1000;
    let shown = 0;
    let deepest = 0;
    for (let i = 0; i < count; i++) {
      if (arrays.missingValueMask[i] || !Number.isFinite(arrays.values[i])) continue;
      index[shown] = i;
      height[shown] = arrays.depth[i] * heightPerDepthUnit;
      deepest = Math.min(deepest, height[shown]);
      shown++;
    }

    const collection = viewer.scene.primitives.add(new PointPrimitiveCollection()) as PointPrimitiveCollection;
    const exaggeration = this.display?.verticalExaggeration ?? 1;
    const points: PointPrimitive[] = new Array(shown);
    for (let k = 0; k < shown; k++) {
      const i = index[k];
      points[k] = collection.add({
        position: Cartesian3.fromDegrees(arrays.longitude[i], arrays.latitude[i], height[k] * exaggeration),
        pixelSize: POINT_PIXELS,
        color: Color.GRAY,
        id: k,
      });
    }
    this.layer = {
      collection, points, bounds, deepest, coloured: false, outline: [],
      source: arrays, index: index.subarray(0, shown), height: height.subarray(0, shown),
    };
    viewer.scene.globe.translucency.rectangle = Rectangle.fromDegrees(
      bounds.west, bounds.south, bounds.east, bounds.north);
    viewer.scene.globe.translucency.enabled = true;
    this.drawOutline(exaggeration);
    if (this.display) this.applyDisplay(this.display);
    this.flyToRegion();
    return { status: "shown", shownPoints: shown, hiddenMissingPoints: count - shown };
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

  showMarkers(set: MarkerSet): MarkerOutcome {
    const viewer = this.viewer;
    if (!viewer) return { status: "refused", reason: "the 3D view is not available" };
    if (!isGeographicCrs(set.crs)) {
      return { status: "refused", reason: `marker coordinate reference system ${set.crs} is not supported by this view` };
    }
    this.clearMarkers();
    const collection = viewer.scene.primitives.add(new PointPrimitiveCollection()) as PointPrimitiveCollection;
    for (let i = 0; i < set.platformIds.length; i++) {
      collection.add({
        position: Cartesian3.fromDegrees(set.longitude[i], set.latitude[i], 0),
        pixelSize: MARKER_PIXELS,
        color: MARKER_FILL,
        outlineColor: Color.WHITE,
        outlineWidth: 2,
        // Never hidden behind the globe or the field: a marker is a handle.
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        id: { marker: i },
      });
    }
    this.markers = { collection, set };
    viewer.scene.requestRender();
    return { status: "shown", count: set.platformIds.length };
  }

  clearMarkers(): void {
    const viewer = this.viewer;
    if (!viewer || !this.markers) return;
    viewer.scene.primitives.remove(this.markers.collection);   // releases GPU resources
    this.markers = undefined;
    viewer.scene.canvas.style.cursor = "";
    viewer.scene.requestRender();
  }

  applyDisplay(display: DisplayState): DisplayOutcome {
    const { minimum, maximum } = display.range;
    const problem = display.scale === "log" ? logScaleProblem(minimum, maximum) : null;
    if (problem) return { status: "refused", reason: problem };   // nothing changed

    const previous = this.display;
    this.display = display;
    const layer = this.layer;
    if (!layer || !this.viewer) return { status: "applied" };

    const { source, index } = layer;
    if (!previous || previous.verticalExaggeration !== display.verticalExaggeration) {
      const e = display.verticalExaggeration;
      for (let k = 0; k < layer.points.length; k++) {
        const i = index[k];
        layer.points[k].position = Cartesian3.fromDegrees(source.longitude[i], source.latitude[i], layer.height[k] * e);
      }
      this.drawOutline(e);
    }

    const recolour = !layer.coloured || !previous || previous.palette !== display.palette ||
      previous.scale !== display.scale || previous.opacity !== display.opacity ||
      previous.range.minimum !== minimum || previous.range.maximum !== maximum;
    if (recolour) {
      for (let k = 0; k < layer.points.length; k++) {
        const [r, g, b] = paletteColour(display.palette,
          normalise(source.values[index[k]], minimum, maximum, display.scale));
        layer.points[k].color = new Color(r, g, b, display.opacity);
      }
      layer.coloured = true;
    }
    this.viewer.scene.requestRender();
    return { status: "applied" };
  }

  async showSurface(field: SurfaceField, style: SurfaceStyle, slot: SurfaceSlot = "base"): Promise<SurfaceOutcome> {
    const viewer = this.viewer;
    if (!viewer) return { status: "refused", reason: "the 3D view is not available" };
    let geometry: GridGeometry;
    let pixels: Uint8ClampedArray<ArrayBuffer>;
    try {
      geometry = gridGeometry(field.longitude, field.latitude);
      const problem = style.scale === "log" ? logScaleProblem(style.range.minimum, style.range.maximum) : null;
      if (problem) return { status: "refused", reason: problem };
      pixels = rasterise(field.values, field.missingValueMask, geometry, style);
    } catch (error) {
      if (error instanceof SurfaceError) return { status: "refused", reason: error.message };
      throw error;
    }
    const generation = ++this.surfaceGeneration[slot];
    const canvas = document.createElement("canvas");
    canvas.width = geometry.columns;
    canvas.height = geometry.rows;
    canvas.getContext("2d")!.putImageData(new ImageData(pixels, geometry.columns, geometry.rows), 0, 0);
    const url = await new Promise<string>((resolve, reject) => canvas.toBlob(
      (blob) => (blob ? resolve(URL.createObjectURL(blob)) : reject(new Error("the surface image could not be encoded"))),
      "image/png"));
    let provider: SingleTileImageryProvider;
    try {
      provider = await SingleTileImageryProvider.fromUrl(url, {
        rectangle: Rectangle.fromDegrees(geometry.imageWest, geometry.south, geometry.imageEast, geometry.north),
      });
    } finally {
      URL.revokeObjectURL(url);
    }
    if (generation !== this.surfaceGeneration[slot] || this.viewer !== viewer) return { status: "superseded" };

    // The new layer goes on top of the old one, which stays visible until the
    // globe has built every tile of the new one; only then is it removed, so
    // an animation step never shows an empty sea.
    const layer = new ImageryLayer(provider, { alpha: SURFACE_ALPHA });
    viewer.imageryLayers.add(layer);
    // Detail always draws above the whole-field layer.
    const detail = this.surfaces.detail;
    if (slot === "base" && detail) viewer.imageryLayers.raiseToTop(detail.layer);
    await tilesSettled(viewer);
    if (generation !== this.surfaceGeneration[slot] || this.viewer !== viewer) {
      if (this.viewer === viewer && !viewer.isDestroyed()) viewer.imageryLayers.remove(layer, true);
      return { status: "superseded" };
    }
    const previous = this.surfaces[slot];
    this.surfaces[slot] = { layer, geometry, field };
    if (previous) viewer.imageryLayers.remove(previous.layer, true);
    this.probedCell = null;
    viewer.scene.requestRender();
    let hidden = 0;
    for (let i = 0; i < field.values.length; i++) {
      if (field.missingValueMask[i] || !Number.isFinite(field.values[i])) hidden++;
    }
    return { status: "shown", shownCells: field.values.length - hidden, hiddenMissingCells: hidden };
  }

  clearSurface(slot?: SurfaceSlot): void {
    for (const which of slot ? [slot] : (["base", "detail"] as const)) {
      this.surfaceGeneration[which]++;   // an image still loading is dropped
      const surface = this.surfaces[which];
      if (!surface || !this.viewer) continue;
      this.viewer.imageryLayers.remove(surface.layer, true);
      delete this.surfaces[which];
    }
    this.setProbe(null);
    this.viewer?.scene.requestRender();
  }

  showArrows(set: ArrowSet, maximumSpeed: number): MarkerOutcome {
    const viewer = this.viewer;
    if (!viewer) return { status: "refused", reason: "the 3D view is not available" };
    this.clearArrows();
    const collection = viewer.scene.primitives.add(new BillboardCollection()) as BillboardCollection;
    const image = arrowImage();
    const ellipsoid = Ellipsoid.WGS84;
    const normal = new Cartesian3();
    const north = new Cartesian3();
    const top = maximumSpeed > 0 ? maximumSpeed : 1;
    for (let i = 0; i < set.longitude.length; i++) {
      const position = Cartesian3.fromDegrees(set.longitude[i], set.latitude[i], ARROW_HEIGHT_M);
      // Local north: the Earth's axis projected onto the tangent plane.
      ellipsoid.geodeticSurfaceNormal(position, normal);
      Cartesian3.subtract(Cartesian3.UNIT_Z, Cartesian3.multiplyByScalar(normal, normal.z, north), north);
      Cartesian3.normalize(north, north);
      const fraction = Math.min(1, set.speed[i] / top);
      collection.add({
        position,
        image,
        width: ARROW_PIXELS, height: ARROW_PIXELS,
        scale: 0.45 + 0.75 * fraction,
        alignedAxis: Cartesian3.clone(north),
        // Bearing clockwise from north; billboard rotation is anticlockwise.
        rotation: -Math.atan2(set.eastward[i], set.northward[i]),
        color: Color.WHITE.withAlpha(0.55 + 0.4 * fraction),
      });
    }
    this.arrows = collection;
    viewer.scene.requestRender();
    return { status: "shown", count: set.longitude.length };
  }

  clearArrows(): void {
    const viewer = this.viewer;
    if (!viewer || !this.arrows) return;
    viewer.scene.primitives.remove(this.arrows);   // releases GPU resources
    this.arrows = undefined;
    viewer.scene.requestRender();
  }

  command(command: RendererCommand): void {
    if (command.type === "resetCamera") this.flyToRegion();
    if (command.type === "flyTo" && this.viewer) {
      const { west, east, south, north } = command;
      this.viewer.camera.flyTo({
        destination: Rectangle.fromDegrees(west, south, east, north),
        duration: 1.6,
      });
    }
  }

  onEvent(listener: (event: RendererEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose(): void {
    this.clearArrows();
    this.clearSurface();
    this.clearMarkers();
    this.clear();
    this.handler?.destroy();
    if (this.viewer && !this.viewer.isDestroyed()) this.viewer.destroy();
    this.viewer = undefined;
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

  private markerIndexAt(position: Cartesian2): number | null {
    const viewer = this.viewer;
    const markers = this.markers;
    if (!viewer || !markers) return null;
    const picked = viewer.scene.pick(position);
    const id = picked?.collection === markers.collection ? picked.id : null;
    return id && typeof id.marker === "number" ? id.marker : null;
  }

  private select(position: Cartesian2): void {
    const index = this.markerIndexAt(position);
    if (index !== null && this.markers) {
      this.emit({ type: "pick", marker: markerPick(this.markers.set, index) });
    }
  }

  private hover(position: Cartesian2): void {
    const viewer = this.viewer;
    if (viewer) viewer.scene.canvas.style.cursor = this.markerIndexAt(position) !== null ? "pointer" : "";
    if (viewer && (this.surfaces.base || this.surfaces.detail)) this.probe(position);
    const layer = this.layer;
    if (!viewer || !layer) return;
    const picked = viewer.scene.pick(position);
    const point = picked?.collection === layer.collection && typeof picked.id === "number" ? picked.id : null;
    this.setHovered(point);
  }

  private setHovered(point: number | null): void {
    if (point === this.hovered) return;
    this.hovered = point;
    const layer = this.layer;
    let sample: PointSample | null = null;
    if (point !== null && layer) {
      const i = layer.index[point];
      const { source } = layer;
      sample = { longitude: source.longitude[i], latitude: source.latitude[i], depth: source.depth[i], value: source.values[i] };
    }
    this.emit({ type: "hover", sample });
  }

  private probe(position: Cartesian2): void {
    const viewer = this.viewer;
    if (!viewer) return;
    const cartesian = viewer.camera.pickEllipsoid(position, Ellipsoid.WGS84);
    if (!cartesian) {
      this.setProbe(null);
      return;
    }
    const where = Cartographic.fromCartesian(cartesian);
    const longitude = CesiumMath.toDegrees(where.longitude);
    const latitude = CesiumMath.toDegrees(where.latitude);
    // The finest layer covering the position answers.
    for (const slot of ["detail", "base"] as const) {
      const surface = this.surfaces[slot];
      if (!surface) continue;
      const cell = cellAt(surface.geometry, longitude, latitude);
      const { field } = surface;
      if (cell === null) continue;
      if (field.missingValueMask[cell] || !Number.isFinite(field.values[cell])) break;
      const key = slot === "detail" ? -1 - cell : cell;
      if (key === this.probedCell) return;
      this.probedCell = key;
      const columns = surface.geometry.columns;
      const sample: SurfaceSample = {
        // The delivered cell's own coordinates, not the pointer's.
        longitude: field.longitude[cell % columns],
        latitude: field.latitude[Math.floor(cell / columns)],
        value: field.values[cell],
        units: field.units,
      };
      if (field.components) {
        sample.eastward = field.components.eastward[cell];
        sample.northward = field.components.northward[cell];
      }
      this.emit({ type: "probe", sample });
      return;
    }
    this.setProbe(null);
  }

  private viewExtent(): Extent | null {
    const viewer = this.viewer;
    if (!viewer) return null;
    const rectangle = viewer.camera.computeViewRectangle(Ellipsoid.WGS84);
    if (!rectangle) return null;
    return {
      west: CesiumMath.toDegrees(rectangle.west), east: CesiumMath.toDegrees(rectangle.east),
      south: CesiumMath.toDegrees(rectangle.south), north: CesiumMath.toDegrees(rectangle.north),
    };
  }

  private setProbe(sample: SurfaceSample | null): void {
    if (sample === null && this.probedCell === null) return;
    this.probedCell = null;
    this.emit({ type: "probe", sample });
  }

  private emit(event: RendererEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}

function extent(longitude: NumericArray, latitude: NumericArray) {
  let west = Infinity, east = -Infinity, south = Infinity, north = -Infinity;
  for (let i = 0; i < longitude.length; i++) {
    west = Math.min(west, longitude[i]); east = Math.max(east, longitude[i]);
    south = Math.min(south, latitude[i]); north = Math.max(north, latitude[i]);
  }
  return { west, east, south, north };
}

/** Longest wait for new tiles before swapping anyway, so a stalled tile
 *  cannot freeze an animation. */
const TILE_WAIT_MS = 4_000;

/** Resolves once the globe reports every visible tile loaded. */
function tilesSettled(viewer: Viewer): Promise<void> {
  return new Promise((resolve) => {
    const { scene } = viewer;
    const started = performance.now();
    let seenLoading = false;
    const check = () => {
      // Adding a layer does not mark tiles dirty until the next frame, so a
      // settled globe is trusted only after that frame has rendered.
      if (!scene.globe.tilesLoaded) seenLoading = true;
      const done = (scene.globe.tilesLoaded && (seenLoading || performance.now() - started > 250))
        || performance.now() - started > TILE_WAIT_MS;
      if (done) {
        remove();
        resolve();
      } else {
        scene.requestRender();
      }
    };
    const remove = scene.postRender.addEventListener(check);
    scene.requestRender();
  });
}

/** Longest texture side used, whatever the GPU allows: every WebGL2 device
 *  supports at least 2048, and 4096 keeps one image near a screen's size. */
const TEXTURE_SIDE_CAP = 4096;

/** The WebGL2 MAX_TEXTURE_SIZE of this browser, capped; the WebGL2 minimum
 *  when it cannot be probed. */
function textureSideLimit(): number {
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    const side = gl?.getParameter(gl.MAX_TEXTURE_SIZE);
    return typeof side === "number" ? Math.min(side, TEXTURE_SIDE_CAP) : 2048;
  } catch {
    return 2048;
  }
}

let arrow: HTMLCanvasElement | undefined;

/** A white arrow pointing up (north before rotation), drawn once. */
function arrowImage(): HTMLCanvasElement {
  if (arrow) return arrow;
  arrow = document.createElement("canvas");
  arrow.width = 32;
  arrow.height = 32;
  const g = arrow.getContext("2d")!;
  g.strokeStyle = "white";
  g.fillStyle = "white";
  g.lineWidth = 3;
  g.lineCap = "round";
  g.beginPath();
  g.moveTo(16, 29);
  g.lineTo(16, 9);
  g.stroke();
  g.beginPath();
  g.moveTo(16, 2);
  g.lineTo(23, 13);
  g.lineTo(9, 13);
  g.closePath();
  g.fill();
  return arrow;
}
