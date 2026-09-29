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
import type { PointFieldArrays, ProductDescriptor } from "../api/wire";

export type PaletteName = "viridis" | "cividis" | "thermal";
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
}

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
  /** The browser cannot run this renderer at all. */
  | { type: "unsupported"; reason: string }
  /** Rendering stopped; a later successfully shown field clears it. */
  | { type: "renderFailed"; reason: string }
  /** The graphics context is gone and this renderer cannot restore it. */
  | { type: "contextLost"; reason: string };

export type RendererCommand = { type: "resetCamera" };

export interface Renderer {
  readonly capabilities: RendererCapabilities;
  mount(container: HTMLElement): void;
  showPointField(descriptor: ProductDescriptor, arrays: PointFieldArrays): FieldOutcome;
  clear(): void;
  /** Observation markers at the sea surface; selecting one emits "pick". */
  showMarkers(markers: MarkerSet): MarkerOutcome;
  clearMarkers(): void;
  applyDisplay(display: DisplayState): DisplayOutcome;
  command(command: RendererCommand): void;
  onEvent(listener: (event: RendererEvent) => void): () => void;
  dispose(): void;
}

/** Chosen once at composition; the UI receives a factory, not an engine. */
export type RendererFactory = () => Renderer;
