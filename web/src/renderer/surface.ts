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
  /** Where the image lies on the globe, in -180..180. imageWest > imageEast
   *  means the image crosses the antimeridian. */
  imageWest: number;
  imageEast: number;
  /** Source column shown in the image's first pixel column: non-zero only
   *  for a whole-globe field in 0..360, rotated to start at -180. */
  firstColumn: number;
}

/** A longitude in -180..180. */
function wrap180(longitude: number): number {
  return ((longitude + 180) % 360 + 360) % 360 - 180;
}

export interface SurfaceStyle {
  palette: PaletteName;
  range: { minimum: number; maximum: number };
  scale: ScaleKind;
}

/** How far any coordinate may sit from its place on the ideal regular grid,
 *  as a fraction of one cell. Source axes are often stored rounded (HYCOM
 *  longitudes to about 1e-4 degrees), so neighbouring steps differ slightly;
 *  what matters for an image is where each cell lands, and 1% of a cell is
 *  far below one pixel. */
const POSITION_TOLERANCE = 0.01;

function step(axis: NumericArray, name: string): number {
  if (axis.length < 2) throw new SurfaceError(`the ${name} axis needs at least two cells`);
  const mean = (axis[axis.length - 1] - axis[0]) / (axis.length - 1);
  if (!Number.isFinite(mean) || mean === 0) throw new SurfaceError(`the ${name} axis is not increasing or decreasing`);
  for (let i = 0; i < axis.length; i++) {
    const offset = Math.abs(axis[i] - (axis[0] + i * mean));
    if (offset > Math.abs(mean) * POSITION_TOLERANCE) {
      throw new SurfaceError(`the ${name} spacing is irregular, so the field cannot be drawn as one image`);
    }
  }
  return mean;
}

export function gridGeometry(longitude: NumericArray, latitude: NumericArray): GridGeometry {
  const longitudeStep = step(longitude, "longitude");
  const latitudeStep = step(latitude, "latitude");
  if (longitudeStep < 0) throw new SurfaceError("longitudes decreasing west to east are not supported");
  const halfLon = longitudeStep / 2;
  const halfLat = Math.abs(latitudeStep) / 2;
  const lats = [latitude[0], latitude[latitude.length - 1]];
  const west = longitude[0] - halfLon;
  const east = longitude[longitude.length - 1] + halfLon;
  // One cell of slack: rounded coordinates may overshoot a full circle.
  if (east - west > 360 + longitudeStep) throw new SurfaceError("the field wraps more than once around the globe");
  // A regional field keeps its columns; one crossing the antimeridian gets
  // imageWest > imageEast, which Cesium draws as a crossing rectangle.
  let imageWest = wrap180(west);
  let imageEast = wrap180(east);
  let firstColumn = 0;
  if (east - west >= 360 - longitudeStep / 2) {
    // A whole globe (HYCOM runs 0..360): rotate the columns so the image
    // starts with the cell whose west edge is nearest the antimeridian. The
    // image then spans -180..180, off by under half a cell.
    let best = Infinity;
    for (let c = 0; c < longitude.length; c++) {
      const fromAntimeridian = wrap180(longitude[c] - halfLon) + 180;
      const distance = Math.min(fromAntimeridian, 360 - fromAntimeridian);
      if (distance < best) { best = distance; firstColumn = c; }
    }
    imageWest = -180;
    imageEast = 180;
  }
  return {
    columns: longitude.length,
    rows: latitude.length,
    west,
    east,
    south: Math.max(-90, Math.min(...lats) - halfLat),
    north: Math.min(90, Math.max(...lats) + halfLat),
    longitudeStep,
    latitudeStep,
    firstLongitude: longitude[0],
    firstLatitude: latitude[0],
    latitudeAscending: latitudeStep > 0,
    imageWest,
    imageEast,
    firstColumn,
  };
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
      const cell = sourceRow * columns + (column + geometry.firstColumn) % columns;
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
