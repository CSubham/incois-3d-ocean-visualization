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
 * The extent to request at detail resolution, in the field's own longitude
 * convention, or null when the whole-field layer is already enough: the
 * base is at source resolution, or most of the field is in view, or the view
 * straddles the field's longitude seam (then the base layer shows it).
 */
export function detailExtent(area: Extent, view: Extent | null, baseFactor: number): Extent | null {
  if (!view || baseFactor <= 1) return null;
  let { west, east } = view;
  if (area.east > 180) {
    // The field runs 0..360: express the view the same way.
    if (west < 0) west += 360;
    if (east < 0) east += 360;
  }
  if (west >= east) return null;   // crosses the seam in the field's convention
  const w = Math.max(area.west, west - span(west, east) * MARGIN);
  const e = Math.min(area.east, east + span(west, east) * MARGIN);
  const s = Math.max(area.south, view.south - (view.north - view.south) * MARGIN);
  const n = Math.min(area.north, view.north + (view.north - view.south) * MARGIN);
  if (w >= e || s >= n) return null;
  const share = ((e - w) * (n - s)) / ((area.east - area.west) * (area.north - area.south));
  if (share >= DETAIL_SHARE) return null;
  return {
    west: Math.max(area.west, Math.floor(w / SNAP) * SNAP),
    east: Math.min(area.east, Math.ceil(e / SNAP) * SNAP),
    south: Math.max(area.south, Math.floor(s / SNAP) * SNAP),
    north: Math.min(area.north, Math.ceil(n / SNAP) * SNAP),
  };
}
