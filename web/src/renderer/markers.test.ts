import { describe, expect, it } from "vitest";

import type { MarkerSet } from "../api/observationWire";
import { markerPick } from "./markers";

const set: MarkerSet = {
  datasetVersionId: "v-argo", crs: "EPSG:4326", verticalKind: "pressure", verticalUnits: "decibar",
  longitude: new Float64Array([73.5, 80.1]), latitude: new Float64Array([8.5, 12.2]),
  verticalMinimum: new Float64Array([2, 1]), verticalMaximum: new Float64Array([10, 2000]),
  platformIds: ["7902250", "5907085"], cycles: ["12", "32"],
  observedAt: ["2026-09-28T00:00:00", "2024-09-02T10:00:00"],
};

describe("markerPick", () => {
  it("returns the exact identity of the selected marker", () => {
    expect(markerPick(set, 1)).toEqual({
      datasetVersionId: "v-argo", platformId: "5907085", cycle: "32",
      longitude: 80.1, latitude: 12.2, observedAt: "2024-09-02T10:00:00",
    });
  });

  it("refuses an index outside the set rather than returning a wrong profile", () => {
    expect(() => markerPick(set, 2)).toThrow(RangeError);
    expect(() => markerPick(set, -1)).toThrow(RangeError);
    expect(() => markerPick(set, 0.5)).toThrow(RangeError);
  });
});
