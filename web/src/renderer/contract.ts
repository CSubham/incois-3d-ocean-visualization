// The S6 renderer facade: the only thing S7 knows about rendering.
//
// S7 hands over renderer-independent products and declarative display state.
// Each hand-over returns its outcome at once, so S7 commits new state only for
// what is actually shown and a refused product leaves the previous one both
// displayed and described. Events carry only what happens later: pointer
// hover, a marker pick, a failed mount, a render failure or a lost context.
// No scene, material, texture or buffer object crosses this boundary, so
// another engine replaces the implementation, not the UI.

import type { MarkerSet } from "../api/observationWire";
import type { NumericArray, PointFieldArrays, ProductDescriptor } from "../api/wire";
import type { SurfaceStyle } from "./surface";

export type { SurfaceStyle } from "./surface";

export type PaletteName = "viridis" | "cividis" | "thermal" | "speed";
export type ScaleKind = "linear" | "log";

export interface DisplayState {
  palette: PaletteName;
  range: { minimum: number; maximum: number };
  scale: ScaleKind;
  opacity: number;
  verticalExaggeration: number;
}

export interface RendererCapabilities {
  engine: string;
  /** Points this renderer accepts in one layer; a configured, not tested, figure. */
  maximumPoints: number;
  /** Cells one surface layer should carry: about a screen's worth. A
   *  configured, not tested, figure; S7 sends it to S5 as the view budget. */
  maximumSurfaceCells: number;
  /** Longest image side this browser's WebGL2 accepts (capped). */
  maximumTextureSide: number;
}

/** Degrees; west > east means the extent crosses the antimeridian. */
export interface Extent { west: number; east: number; south: number; north: number }

/** The coarse layer covers the whole field; the detail layer covers what is
 *  in view at finer resolution and is drawn above it. */
export type SurfaceSlot = "base" | "detail";

/** One source cell under the pointer, in physical terms. */
export interface PointSample {
  longitude: number;
  latitude: number;
  depth: number;
  value: number;
}

/** The exact profile a selected marker stands for, with where and when. */
export interface MarkerPick {
  datasetVersionId: string;
  platformId: string;
  cycle: string;
  longitude: number;
  latitude: number;
  observedAt: string;
}

/** One horizontal level on a regular longitude/latitude grid, draped on the
 *  globe. Values are flat, row-major over (latitude, longitude). */
export interface SurfaceField {
  longitude: NumericArray;
  latitude: NumericArray;
  values: NumericArray;
  missingValueMask: Uint8Array;
  units: string;
  /** A vector field's components; ``values`` then holds its speed. */
  components?: { eastward: NumericArray; northward: NumericArray };
}

/** One surface cell under the pointer, with its exact source values. */
export interface SurfaceSample {
  longitude: number;
  latitude: number;
  value: number;
  units: string;
  eastward?: number;
  northward?: number;
}

/** Arrows at explicitly sampled cells of a vector field (sampling is S4's). */
export interface ArrowSet {
  longitude: NumericArray;
  latitude: NumericArray;
  eastward: NumericArray;
  northward: NumericArray;
  speed: NumericArray;
}

export type SurfaceOutcome =
  | { status: "shown"; shownCells: number; hiddenMissingCells: number }
  /** Not drawn; the previous surface, if any, is still displayed. */
  | { status: "refused"; reason: string }
  /** A later hand-over replaced this one before it was drawn. */
  | { status: "superseded" };

/** What became of a point field handed to the renderer. */
export type FieldOutcome =
  | { status: "shown"; shownPoints: number; hiddenMissingPoints: number }
  /** Not drawn; the previous field, if any, is still displayed unchanged. */
  | { status: "refused"; reason: string }
  /** Not drawn; a request at ``retryWithPoints`` would be accepted. */
  | { status: "too-large"; reason: string; retryWithPoints: number };

export type MarkerOutcome =
  | { status: "shown"; count: number }
  | { status: "refused"; reason: string };

export type DisplayOutcome =
  | { status: "applied" }
  | { status: "refused"; reason: string };

export type RendererEvent =
  | { type: "pick"; marker: MarkerPick }
  | { type: "hover"; sample: PointSample | null }
  /** The surface cell under the pointer, or null off the surface. */
  | { type: "probe"; sample: SurfaceSample | null }
  /** The camera came to rest; null when no part of the globe is in view. */
  | { type: "view"; extent: Extent | null }
  /** The browser cannot run this renderer at all. */
  | { type: "unsupported"; reason: string }
  /** Rendering stopped; a later successfully shown field clears it. */
  | { type: "renderFailed"; reason: string }
  /** The graphics context is gone and this renderer cannot restore it. */
  | { type: "contextLost"; reason: string };

export type RendererCommand =
  | { type: "resetCamera" }
  | { type: "flyTo"; west: number; east: number; south: number; north: number };

export interface Renderer {
  readonly capabilities: RendererCapabilities;
  mount(container: HTMLElement): void;
  showPointField(descriptor: ProductDescriptor, arrays: PointFieldArrays): FieldOutcome;
  clear(): void;
  /** Observation markers at the sea surface; selecting one emits "pick". */
  showMarkers(markers: MarkerSet): MarkerOutcome;
  clearMarkers(): void;
  applyDisplay(display: DisplayState): DisplayOutcome;
  /** Replace the draped surface layer once the new image is ready, so an
   *  animation never flashes an empty globe. */
  showSurface(field: SurfaceField, style: SurfaceStyle, slot?: SurfaceSlot): Promise<SurfaceOutcome>;
  /** Clears one slot, or both when none is named. */
  clearSurface(slot?: SurfaceSlot): void;
  showArrows(arrows: ArrowSet, maximumSpeed: number): MarkerOutcome;
  clearArrows(): void;
  command(command: RendererCommand): void;
  onEvent(listener: (event: RendererEvent) => void): () => void;
  dispose(): void;
}

/** Chosen once at composition; the UI receives a factory, not an engine. */
export type RendererFactory = () => Renderer;
