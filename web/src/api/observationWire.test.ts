import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { decodeMarkers, decodeProfile, type MarkerDescriptor, type ProfileDescriptor } from "./observationWire";
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

  it("carries the markers' coordinate reference", () => {
    expect(decodeMarkers(descriptor, buffer).crs).toBe("EPSG:4326");
  });

  it("accepts source-preserved float32 markers exactly as S5 declares them", () => {
    const f4 = JSON.parse(readFileSync(new URL("observation-markers-f4.json", fixture), "utf8")) as MarkerDescriptor;
    const raw = readFileSync(new URL("observation-markers-f4.bin", fixture));
    const markers = decodeMarkers(f4, raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) as ArrayBuffer);
    expect(markers.platformIds).toEqual(["5901", "5902"]);
    expect(markers.cycles).toEqual(["7", "8"]);
    expect(markers.longitude).toBeInstanceOf(Float32Array);
    // Not widened or narrowed: the float32 value S5 sent, bit for bit.
    expect(markers.longitude[1]).toBe(Math.fround(82.1));
    expect(markers.latitude[0]).toBe(-4);
  });

  it("refuses integer marker coordinates", () => {
    const tampered = structuredClone(descriptor);
    tampered.data.arrays.find((a) => a.name === "longitude")!.dtype = "<i4";
    expect(() => decodeMarkers(tampered, buffer)).toThrow(/floating point/);
  });

  it("refuses a truncated buffer or an unknown format", () => {
    expect(() => decodeMarkers(descriptor, buffer.slice(8))).toThrow(WireError);
    expect(() => decodeMarkers({ ...descriptor, wire_format: "other/1" }, buffer)).toThrow(WireError);
  });
});

describe("decodeProfile", () => {
  const profileDescriptor = JSON.parse(readFileSync(new URL("observation-profile.json", fixture), "utf8")) as ProfileDescriptor;
  const raw = readFileSync(new URL("observation-profile.bin", fixture));
  const profileBuffer = raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength) as ArrayBuffer;

  it("reads one exact profile with its pressure axis", () => {
    const profile = decodeProfile(profileDescriptor, profileBuffer);
    expect([profile.platformId, profile.cycle]).toEqual(["7902250", "12"]);
    expect(profile.verticalKind).toBe("pressure");
    expect(profile.verticalUnits).toBe("decibar");
    expect(Array.from(profile.vertical)).toEqual([2, 10]);
    expect(profile.timestamps.every((t) => t?.startsWith("2026-09-28"))).toBe(true);
    expect(profile.variables.map((v) => [v.name, v.units])).toEqual([["TEMP", "degree_Celsius"], ["PSAL", "1e-3"]]);
  });

  it("carries QC flags with their declared meanings, and none where none are declared", () => {
    const [temp, psal] = decodeProfile(profileDescriptor, profileBuffer).variables;
    expect(temp.qcFlags).toHaveLength(2);
    expect(temp.qcMeanings?.get("1")).toBe("good data");
    expect(temp.qcMeanings?.get("2")).toBe("bad data");
    expect(psal.qcFlags).toHaveLength(2);
    expect(psal.qcMeanings).toBeNull();
  });

  it("refuses a truncated buffer", () => {
    expect(() => decodeProfile(profileDescriptor, profileBuffer.slice(8))).toThrow(WireError);
  });
});
