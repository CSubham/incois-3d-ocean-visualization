// The S6 renderer facade: the only thing S7 knows about rendering.
//
// S7 hands over renderer-independent products and declarative display state,
// and receives events. No scene, material, texture or buffer object crosses
// this boundary, so another engine replaces the implementation, not the UI.

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

export type RendererEvent =
  | { type: "ready"; shownPoints: number; hiddenMissingPoints: number }
  | { type: "markersReady"; count: number }
  | { type: "pick"; marker: MarkerPick }
  | { type: "hover"; sample: PointSample | null }
  | { type: "unsupported"; reason: string }
  | { type: "resource"; reason: string; retryWithPoints: number }
  | { type: "error"; reason: string };

export type RendererCommand = { type: "resetCamera" };

export interface Renderer {
  readonly capabilities: RendererCapabilities;
  mount(container: HTMLElement): void;
  showPointField(descriptor: ProductDescriptor, arrays: PointFieldArrays): void;
  clear(): void;
  /** Observation markers at the sea surface; selecting one emits "pick". */
  showMarkers(markers: MarkerSet): void;
  clearMarkers(): void;
  applyDisplay(display: DisplayState): void;
  command(command: RendererCommand): void;
  onEvent(listener: (event: RendererEvent) => void): () => void;
  dispose(): void;
}

/** Chosen once at composition; the UI receives a factory, not an engine. */
export type RendererFactory = () => Renderer;
