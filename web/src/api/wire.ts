// Decoder for the S5 point-field wire format (serving/wire.py).
//
// The descriptor states each array's dtype, count and byte offset; arrays are
// little-endian and eight-byte aligned, so each becomes a typed-array view on
// the one buffer without copying. Nothing is inferred from sizes.

export const WIRE_FORMAT = "s5.point-field-wire/1.0";

export interface ArrayLayout {
  name: string;
  dtype: string;
  count: number;
  byte_offset: number;
  byte_length: number;
  components?: string[];
}

export interface Range {
  minimum: number | null;
  maximum: number | null;
  valid_point_count: number;
  missing_point_count: number;
}

export interface Sampling {
  policy: string;
  parameters: Record<string, unknown>;
  maximum_points: number;
  original_point_count: number;
  original_valid_point_count: number;
  delivered_point_count: number;
  delivered_valid_point_count: number;
  omitted_point_count: number;
  is_lossy: boolean;
}

export interface ProductMetadata {
  schema_version: string;
  product_type: string;
  identity: {
    dataset_id: string;
    dataset_version_id: string;
    variable: string;
    time_coordinate: string;
    time_value: string;
  };
  coordinates: {
    units: Record<string, string | null>;
    dtypes: Record<string, string>;
    time_encoding: Record<string, string | null>;
  };
  spatial_reference: { crs: string; vertical_positive: "down" | "up" };
  coordinate_transform: { kind: string; horizontal: string; vertical: string };
  mask_semantics: { true_means: string; sources: string[]; masked_values: string };
  variable_units: string;
  source_dtype: string;
  provenance: Record<string, unknown>;
  sampling: Sampling;
  full_subset_range: Range;
  delivered_sample_range: Range;
}

export interface ProductDescriptor {
  wire_format: string;
  product: ProductMetadata;
  point_count: number;
  data: {
    url: string;
    media_type: string;
    byte_order: string;
    byte_length: number;
    arrays: ArrayLayout[];
  };
}

export type NumericArray =
  | Float32Array | Float64Array | Int8Array | Int16Array | Int32Array
  | Uint8Array | Uint16Array | Uint32Array;

export interface PointFieldArrays {
  longitude: NumericArray;
  latitude: NumericArray;
  depth: NumericArray;
  values: NumericArray;
  missingValueMask: Uint8Array;
}

export class WireError extends Error {}

const VIEWS: Record<string, new (buffer: ArrayBuffer, offset: number, length: number) => NumericArray> = {
  "<f4": Float32Array, "<f8": Float64Array,
  "|i1": Int8Array, "<i2": Int16Array, "<i4": Int32Array,
  "|u1": Uint8Array, "<u2": Uint16Array, "<u4": Uint32Array,
};

export function view(layout: ArrayLayout, buffer: ArrayBuffer): NumericArray {
  const View = VIEWS[layout.dtype];
  if (!View) throw new WireError(`${layout.name} has unsupported dtype ${layout.dtype}`);
  if (layout.byte_offset + layout.byte_length > buffer.byteLength) {
    throw new WireError(`${layout.name} extends past the end of the data`);
  }
  return new View(buffer, layout.byte_offset, layout.count);
}

export function decodePointField(descriptor: ProductDescriptor, buffer: ArrayBuffer): PointFieldArrays {
  if (descriptor.wire_format !== WIRE_FORMAT) {
    throw new WireError(`unsupported wire format ${descriptor.wire_format}`);
  }
  if (buffer.byteLength !== descriptor.data.byte_length) {
    throw new WireError(
      `expected ${descriptor.data.byte_length} bytes, received ${buffer.byteLength}`);
  }
  const byName = new Map(descriptor.data.arrays.map((a) => [a.name, a]));
  const take = (name: string) => {
    const layout = byName.get(name);
    if (!layout) throw new WireError(`the data has no ${name} array`);
    const array = view(layout, buffer);
    if (array.length !== descriptor.point_count) {
      throw new WireError(`${name} has ${array.length} entries, expected ${descriptor.point_count}`);
    }
    return array;
  };
  const mask = take("missing_value_mask");
  if (!(mask instanceof Uint8Array)) throw new WireError("missing_value_mask must be uint8");
  return {
    longitude: take("longitude"),
    latitude: take("latitude"),
    depth: take("depth"),
    values: take("values"),
    missingValueMask: mask,
  };
}
