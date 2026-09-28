// Engine-independent marker helpers shared by every renderer implementation.

import type { MarkerSet } from "../api/observationWire";
import type { MarkerPick } from "./contract";

/** The exact identity and position of marker ``index`` in a set. */
export function markerPick(set: MarkerSet, index: number): MarkerPick {
  if (!Number.isInteger(index) || index < 0 || index >= set.platformIds.length) {
    throw new RangeError(`no marker ${index} in a set of ${set.platformIds.length}`);
  }
  return {
    datasetVersionId: set.datasetVersionId,
    platformId: set.platformIds[index],
    cycle: set.cycles[index],
    longitude: set.longitude[index],
    latitude: set.latitude[index],
    observedAt: set.observedAt[index],
  };
}
