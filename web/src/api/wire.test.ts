import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { decodePointField, WireError, type ProductDescriptor } from "./wire";

// Written by serving/tests/test_wire.py from the Python encoder.
const fixture = new URL("../../test-fixtures/", import.meta.url);
const descriptor = JSON.parse(readFileSync(new URL("point-field.json", fixture), "utf8")) as ProductDescriptor;
const bytes = readFileSync(new URL("point-field.bin", fixture));
const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;

describe("decodePointField", () => {
  it("reads the arrays the Python encoder wrote, value for value", () => {
    const arrays = decodePointField(descriptor, buffer);
    // Fixture grid: value = 36t + 12d + 4lat + lon at the recorded indices.
    expect(Array.from(arrays.values.slice(1))).toEqual([55, 59, 67, 71]);
    expect(Number.isNaN(arrays.values[0])).toBe(true);
    expect(Array.from(arrays.missingValueMask)).toEqual([1, 0, 0, 0, 0]);
    expect(Array.from(arrays.longitude)).toEqual([70, 90, 90, 90, 90]);
    expect(Array.from(arrays.latitude)).toEqual([0, 0, 10, 0, 10]);
    expect(Array.from(arrays.depth)).toEqual([10, 10, 10, 20, 20]);
    expect(arrays.values).toBeInstanceOf(Float32Array);
  });

  it("carries the scientific facts the view discloses", () => {
    const p = descriptor.product;
    expect(p.spatial_reference).toEqual({ crs: "EPSG:4326", vertical_positive: "down" });
    expect(p.sampling.original_point_count).toBe(12);
    expect(p.sampling.delivered_valid_point_count).toBe(4);
    expect(p.coordinates.units.depth).toBe("m");
  });

  it("refuses a buffer of the wrong length or an unknown format", () => {
    expect(() => decodePointField(descriptor, buffer.slice(8))).toThrow(WireError);
    expect(() => decodePointField({ ...descriptor, wire_format: "other/2" }, buffer)).toThrow(WireError);
  });
});
