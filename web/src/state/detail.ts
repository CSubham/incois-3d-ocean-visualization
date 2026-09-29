// When the view deserves a finer layer than the whole-field one, and where.
// Pure: S7 decides what to request; S4 decides how to fit it to the budget.

import type { Extent } from "../renderer/contract";

/** Below this share of the field's area in view, a detail layer is requested. */
const DETAIL_SHARE = 0.5;
/** Margin around the view, as a share of its size, so small pans stay covered. */
const MARGIN = 0.1;
/** Extents snap outward to this grid (degrees), so nearby views share products. */
const SNAP = 0.5;

function span(west: number, east: number): number {
  return east - west;
}

/**
 * The extent to request at detail resolution, or null when the whole-field
 * layer is already enough: the base is at source resolution, or most of the
 * field is in view. Longitudes go to S4 in either convention; a view across
 * the antimeridian is sent with east beyond 180 (S4 selects by angle).
 */
export function detailExtent(area: Extent, view: Extent | null, baseFactor: number): Extent | null {
  if (!view || baseFactor <= 1) return null;
  const west = view.west;
  const east = view.east < view.west ? view.east + 360 : view.east;
  const globe = area.east - area.west >= 359;
  const lonSpan = span(west, east);
  const w = globe ? west - lonSpan * MARGIN : Math.max(area.west, west - lonSpan * MARGIN);
  const e = globe ? east + lonSpan * MARGIN : Math.min(area.east, east + lonSpan * MARGIN);
  const s = Math.max(area.south, view.south - (view.north - view.south) * MARGIN);
  const n = Math.min(area.north, view.north + (view.north - view.south) * MARGIN);
  if (w >= e || s >= n) return null;
  const areaSpan = globe ? 360 : area.east - area.west;
  const share = ((e - w) * (n - s)) / (areaSpan * (area.north - area.south));
  if (share >= DETAIL_SHARE || e - w >= 360) return null;
  const snappedWest = Math.floor(w / SNAP) * SNAP;
  const snappedEast = Math.ceil(e / SNAP) * SNAP;
  return {
    west: globe ? snappedWest : Math.max(area.west, snappedWest),
    east: globe ? snappedEast : Math.min(area.east, snappedEast),
    south: Math.max(area.south, Math.floor(s / SNAP) * SNAP),
    north: Math.min(area.north, Math.ceil(n / SNAP) * SNAP),
  };
}
