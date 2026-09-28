// Three.js on WebGL2: the first implementation of the renderer facade.
//
// Owns every scene object, GPU buffer and frame. Positions are uploaded once
// in the local km frame without exaggeration; exaggeration is the layer
// group's y scale, so changing it never touches physical values. Masked and
// non-finite cells are not uploaded, and how many were left out is reported.

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { PointFieldArrays, ProductDescriptor } from "../../api/wire";
import { logScaleProblem, normalise, paletteColour } from "../colour";
import type {
  DisplayState, Renderer, RendererCapabilities, RendererCommand, RendererEvent,
} from "../contract";
import { sceneFrame, toScene, TransformError } from "../transform";

interface Layer {
  points: THREE.Points;
  outline: THREE.LineSegments;
  values: Float32Array;
  coloured: boolean;
}

export class ThreeRenderer implements Renderer {
  readonly capabilities: RendererCapabilities;
  private readonly listeners = new Set<(event: RendererEvent) => void>();
  private renderer?: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100_000);
  private readonly group = new THREE.Group();
  private controls?: OrbitControls;
  private resizeObserver?: ResizeObserver;
  private container?: HTMLElement;
  private layer?: Layer;
  private display?: DisplayState;
  private frameRequested = false;

  constructor(maximumPoints: number) {
    this.capabilities = { engine: `three.js r${THREE.REVISION} on WebGL2`, maximumPoints };
    this.scene.background = new THREE.Color("#0b1622");
    this.scene.add(this.group);
  }

  mount(container: HTMLElement): void {
    this.container = container;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2");
    if (!context) {
      this.emit({ type: "unsupported", reason: "this browser does not provide WebGL2, which the 3D view requires" });
      return;
    }
    this.renderer = new THREE.WebGLRenderer({ canvas, context, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(canvas);
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      this.emit({ type: "error", reason: "the graphics context was lost; reload to restore the view" });
    });
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false;
    this.controls.addEventListener("change", () => this.requestFrame());
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
  }

  showPointField(descriptor: ProductDescriptor, arrays: PointFieldArrays): void {
    if (!this.renderer) return;
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

    const count = arrays.values.length;
    const positions = new Float32Array(count * 3);
    const values = new Float32Array(count);
    const depths = new Set<number>();
    let shown = 0;
    let deepest = 0;
    for (let i = 0; i < count; i++) {
      const value = arrays.values[i];
      if (arrays.missingValueMask[i] || !Number.isFinite(value)) continue;
      const [x, y, z] = toScene(frame, arrays.longitude[i], arrays.latitude[i], arrays.depth[i]);
      positions.set([x, y, z], shown * 3);
      values[shown] = value;
      depths.add(arrays.depth[i]);
      deepest = Math.min(deepest, y);
      shown++;
    }

    this.clear();
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions.subarray(0, shown * 3), 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(shown * 3), 3));
    const [west, , north] = toScene(frame, bounds.west, bounds.north, 0);
    const [east, , south] = toScene(frame, bounds.east, bounds.south, 0);
    const width = east - west;
    const length = south - north;
    const columns = Math.max(1, shown / Math.max(1, depths.size));
    const material = new THREE.PointsMaterial({
      size: 0.9 * Math.sqrt((width * length) / columns),
      vertexColors: true,
      sizeAttenuation: true,
    });
    const points = new THREE.Points(geometry, material);
    const outline = boxOutline(west, east, north, south, deepest);
    this.group.add(points, outline);
    this.layer = { points, outline, values: values.subarray(0, shown), coloured: false };

    if (this.display) this.applyDisplay(this.display);
    this.fitCamera();
    this.emit({ type: "ready", shownPoints: shown, hiddenMissingPoints: count - shown });
  }

  clear(): void {
    if (!this.layer) return;
    for (const object of [this.layer.points, this.layer.outline]) {
      this.group.remove(object);
      object.geometry.dispose();
      (object.material as THREE.Material).dispose();
    }
    this.layer = undefined;
    this.requestFrame();
  }

  applyDisplay(display: DisplayState): void {
    const previous = this.display;
    this.display = display;
    this.group.scale.y = display.verticalExaggeration;
    const layer = this.layer;
    if (!layer) return this.requestFrame();

    const material = layer.points.material as THREE.PointsMaterial;
    material.opacity = display.opacity;
    material.transparent = display.opacity < 1;
    material.depthWrite = display.opacity >= 1;
    material.needsUpdate = true;

    const recolour = !previous || previous.palette !== display.palette ||
      previous.scale !== display.scale ||
      previous.range.minimum !== display.range.minimum ||
      previous.range.maximum !== display.range.maximum || !layer.coloured;
    if (recolour) {
      const { minimum, maximum } = display.range;
      if (display.scale === "log" && logScaleProblem(minimum, maximum)) {
        this.emit({ type: "error", reason: logScaleProblem(minimum, maximum)! });
      } else {
        const colours = layer.points.geometry.getAttribute("color") as THREE.BufferAttribute;
        const array = colours.array as Float32Array;
        for (let i = 0; i < layer.values.length; i++) {
          const t = normalise(layer.values[i], minimum, maximum, display.scale);
          array.set(paletteColour(display.palette, t), i * 3);
        }
        colours.needsUpdate = true;
        layer.coloured = true;
      }
    }
    this.requestFrame();
  }

  command(command: RendererCommand): void {
    if (command.type === "resetCamera") this.fitCamera();
  }

  onEvent(listener: (event: RendererEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  dispose(): void {
    this.clear();
    this.resizeObserver?.disconnect();
    this.controls?.dispose();
    this.renderer?.dispose();
    this.renderer?.domElement.remove();
    this.renderer = undefined;
    this.listeners.clear();
  }

  private fitCamera(): void {
    const box = new THREE.Box3().setFromObject(this.group);
    if (box.isEmpty()) return this.requestFrame();
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const distance = sphere.radius / Math.sin((this.camera.fov * Math.PI) / 360);
    this.camera.position.copy(sphere.center).add(new THREE.Vector3(0.55, 0.6, 1).normalize().multiplyScalar(distance));
    this.camera.near = distance / 100;
    this.camera.far = distance * 10;
    this.camera.updateProjectionMatrix();
    this.controls?.target.copy(sphere.center);
    this.controls?.update();
    this.requestFrame();
  }

  private resize(): void {
    if (!this.renderer || !this.container) return;
    const { clientWidth: width, clientHeight: height } = this.container;
    this.renderer.setSize(width, height, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.camera.aspect = width / Math.max(1, height);
    this.camera.updateProjectionMatrix();
    this.requestFrame();
  }

  // Render on demand: a static field costs no GPU time between changes.
  private requestFrame(): void {
    if (this.frameRequested || !this.renderer) return;
    this.frameRequested = true;
    requestAnimationFrame(() => {
      this.frameRequested = false;
      this.renderer?.render(this.scene, this.camera);
    });
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

// The region's sea surface and deepest shown level, as a wire box.
function boxOutline(west: number, east: number, north: number, south: number, bottom: number): THREE.LineSegments {
  const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(east - west, -bottom || 0.001, south - north));
  geometry.translate((west + east) / 2, bottom / 2, (north + south) / 2);
  return new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: "#5d7a94" }));
}
