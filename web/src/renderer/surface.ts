// Surface fields as images: grid geometry, colouring and cell lookup.
// Pure: no rendering engine involved, so every rule here is unit-tested.
//
// A surface field is drawn as one texture draped on the globe, which is
// only faithful when its cells are evenly spaced in longitude and latitude;
// an irregular grid is refused rather than silently stretched. Each pixel is
// one source cell, so nothing is resampled here; missing cells (land) are
// fully transparent.

import type { NumericArray } from "../api/wire";
import { normalise, paletteColour } from "./colour";
import type { PaletteName, ScaleKind } from "./contract";

export class SurfaceError extends Error {}

export interface GridGeometry {
  columns: number;
  rows: number;
  /** Outer cell edges in degrees; cells are centred on the source coordinates. */
  west: number; east: number; south: number; north: number;
  longitudeStep: number;
  latitudeStep: number;
  firstLongitude: number;
  firstLatitude: number;
  /** Source rows run south to north. */
  latitudeAscending: boolean;
}

export interface SurfaceStyle {
  palette: PaletteName;
  range: { minimum: number; maximum: number };
  scale: ScaleKind;
}

/** Relative spacing tolerance: float coordinates of a regular grid wobble. */
const SPACING_TOLERANCE = 1e-3;

function step(axis: NumericArray, name: string): number {
  if (axis.length < 2) throw new SurfaceError(`the ${name} axis needs at least two cells`);
  const first = axis[1] - axis[0];
  if (!Number.isFinite(first) || first === 0) throw new SurfaceError(`the ${name} axis is not increasing or decreasing`);
  for (let i = 2; i < axis.length; i++) {
    const d = axis[i] - axis[i - 1];
    if (Math.abs(d - first) > Math.abs(first) * SPACING_TOLERANCE) {
      throw new SurfaceError(`the ${name} spacing is irregular, so the field cannot be drawn as one image`);
    }
  }
  // The mean step over the whole axis, not one rounded difference.
  return (axis[axis.length - 1] - axis[0]) / (axis.length - 1);
}

export function gridGeometry(longitude: NumericArray, latitude: NumericArray): GridGeometry {
  const longitudeStep = step(longitude, "longitude");
  const latitudeStep = step(latitude, "latitude");
  if (longitudeStep < 0) throw new SurfaceError("longitudes decreasing west to east are not supported");
  const halfLon = longitudeStep / 2;
  const halfLat = Math.abs(latitudeStep) / 2;
  const lats = [latitude[0], latitude[latitude.length - 1]];
  const geometry = {
    columns: longitude.length,
    rows: latitude.length,
    west: longitude[0] - halfLon,
    east: longitude[longitude.length - 1] + halfLon,
    south: Math.max(-90, Math.min(...lats) - halfLat),
    north: Math.min(90, Math.max(...lats) + halfLat),
    longitudeStep,
    latitudeStep,
    firstLongitude: longitude[0],
    firstLatitude: latitude[0],
    latitudeAscending: latitudeStep > 0,
  };
  if (geometry.east - geometry.west > 360) throw new SurfaceError("the field wraps more than once around the globe");
  return geometry;
}

/** RGBA pixels, north row first, one pixel per source cell. */
export function rasterise(values: NumericArray, mask: Uint8Array, geometry: GridGeometry,
                          style: SurfaceStyle): Uint8ClampedArray<ArrayBuffer> {
  const { columns, rows } = geometry;
  if (values.length !== columns * rows || mask.length !== values.length) {
    throw new SurfaceError("the field values do not match its grid");
  }
  const pixels = new Uint8ClampedArray(columns * rows * 4);
  const { minimum, maximum } = style.range;
  for (let row = 0; row < rows; row++) {
    const sourceRow = geometry.latitudeAscending ? rows - 1 - row : row;
    for (let column = 0; column < columns; column++) {
      const cell = sourceRow * columns + column;
      const value = values[cell];
      if (mask[cell] || !Number.isFinite(value)) continue;   // transparent
      const [r, g, b] = paletteColour(style.palette, normalise(value, minimum, maximum, style.scale));
      const p = (row * columns + column) * 4;
      pixels[p] = r * 255;
      pixels[p + 1] = g * 255;
      pixels[p + 2] = b * 255;
      pixels[p + 3] = 255;
    }
  }
  return pixels;
}

/** The source cell containing a position, or null outside the grid. */
export function cellAt(geometry: GridGeometry, longitude: number, latitude: number): number | null {
  let lon = longitude;
  while (lon < geometry.west) lon += 360;
  while (lon >= geometry.east) lon -= 360;
  if (lon < geometry.west || latitude < geometry.south || latitude > geometry.north) return null;
  const column = Math.round((lon - geometry.firstLongitude) / geometry.longitudeStep);
  const row = Math.round((latitude - geometry.firstLatitude) / geometry.latitudeStep);
  if (column < 0 || column >= geometry.columns || row < 0 || row >= geometry.rows) return null;
  return row * geometry.columns + column;
}

/** A display range covering the central 98% of valid values, so a few
 *  extreme cells do not wash out the colour of everything else. */
export function robustRange(values: NumericArray, mask: Uint8Array): { minimum: number; maximum: number } | null {
  let lo = Infinity, hi = -Infinity, valid = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (mask[i] || !Number.isFinite(v)) continue;
    lo = Math.min(lo, v); hi = Math.max(hi, v); valid++;
  }
  if (valid === 0) return null;
  if (hi === lo) return { minimum: lo, maximum: hi + 1 };
  const bins = new Uint32Array(1024);
  const width = (hi - lo) / bins.length;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (mask[i] || !Number.isFinite(v)) continue;
    bins[Math.min(bins.length - 1, Math.floor((v - lo) / width))]++;
  }
  // The bin holding quantile q: its lower edge bounds from below, its upper
  // edge from above, so the range never cuts inside a bin.
  const binOf = (q: number) => {
    let seen = 0;
    for (let b = 0; b < bins.length; b++) {
      seen += bins[b];
      if (seen >= q * valid) return b;
    }
    return bins.length - 1;
  };
  return { minimum: lo + binOf(0.01) * width, maximum: lo + (binOf(0.99) + 1) * width };
}
