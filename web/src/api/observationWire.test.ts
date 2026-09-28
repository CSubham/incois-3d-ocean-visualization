import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { decodeMarkers, type MarkerDescriptor } from "./observationWire";
import { WireError } from "./wire";

// Written by serving/tests/test_wire_observation.py from the Python encoder.
const fixture = new URL("../../test-fixtures/", import.meta.url);
const descriptor = JSON.parse(readFileSync(new URL("observation-markers.json", fixture), "utf8")) as MarkerDescriptor;
const bytes = readFileSync(new URL("observation-markers.bin", fixture));
const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;

describe("decodeMarkers", () => {
  it("reads the markers the Python encoder wrote, with exact identity", () => {
    const markers = decodeMarkers(descriptor, buffer);
    expect(markers.platformIds).toEqual(["7902250"]);
    expect(markers.cycles).toEqual(["12"]);
    expect(Array.from(markers.longitude)).toEqual([73.5]);
    expect(Array.from(markers.latitude)).toEqual([8.5]);
    expect(markers.observedAt[0]).toMatch(/^2026-09-28/);
    expect(markers.datasetVersionId).toBe("profile-version-1");
  });

  it("keeps pressure as pressure", () => {
    const markers = decodeMarkers(descriptor, buffer);
    expect(markers.verticalKind).toBe("pressure");
    expect(markers.verticalUnits).toBe("decibar");
    expect(Array.from(markers.verticalMinimum)).toEqual([2]);
    expect(Array.from(markers.verticalMaximum)).toEqual([10]);
  });

  it("refuses a truncated buffer or an unknown format", () => {
    expect(() => decodeMarkers(descriptor, buffer.slice(8))).toThrow(WireError);
    expect(() => decodeMarkers({ ...descriptor, wire_format: "other/1" }, buffer)).toThrow(WireError);
  });
});
