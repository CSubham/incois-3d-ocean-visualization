// Decoders for the S5 surface-slice wire formats (serving/wire_slice.py and
// serving/wire_vector.py). Arrays arrive flat, row-major over grid_shape
// (latitude, longitude); each becomes a view on the one buffer.

import { view, WireError, type ArrayLayout, type NumericArray, type Range } from "./wire";

export const SLICE_WIRE_FORMAT = "s5.depth-slice-wire/1.0";
export const VECTOR_WIRE_FORMAT = "s5.vector-slice-wire/1.0";

interface DataSection {
  url: string;
  media_type: string;
  byte_order: string;
  byte_length: number;
  arrays: ArrayLayout[];
}

interface SliceMetadata {
  identity: { dataset_id: string; dataset_version_id: string; variable: string; time_value: string };
  variable_units: string;
  physical_range: Range;
  interpolation: { delivered_depth: number; is_interpolated: boolean };
  spatial_reference: { crs: string };
}

export interface SliceDescriptor {
  wire_format: string;
  product: SliceMetadata;
  grid_shape: [number, number];
  data: DataSection;
}

export interface VectorDescriptor {
  wire_format: string;
  product: {
    units: string;
    speed_range: Range;
    eastward: SliceMetadata;
    northward: SliceMetadata;
  };
  grid_shape: [number, number];
  data: DataSection;
}

/** One horizontal grid: 1-D axes and flat row-major values over (lat, lon). */
export interface SurfaceArrays {
  longitude: NumericArray;
  latitude: NumericArray;
  values: NumericArray;
  missingValueMask: Uint8Array;
}

export interface VectorArrays extends SurfaceArrays {
  /** values holds the derived speed; the components are kept exactly. */
  eastward: NumericArray;
  northward: NumericArray;
}

interface Reader {
  rows: number;
  columns: number;
  take(name: string, count: number): NumericArray;
}

function reader(descriptor: { wire_format: string; grid_shape: [number, number]; data: DataSection },
                expected: string, buffer: ArrayBuffer): Reader {
  if (descriptor.wire_format !== expected) {
    throw new WireError(`unsupported wire format ${descriptor.wire_format}`);
  }
  if (buffer.byteLength !== descriptor.data.byte_length) {
    throw new WireError(`expected ${descriptor.data.byte_length} bytes, received ${buffer.byteLength}`);
  }
  const [rows, columns] = descriptor.grid_shape;
  const byName = new Map(descriptor.data.arrays.map((a) => [a.name, a]));
  return {
    rows, columns,
    take(name, count) {
      const layout = byName.get(name);
      if (!layout) throw new WireError(`the data has no ${name} array`);
      const array = view(layout, buffer);
      if (array.length !== count) throw new WireError(`${name} has ${array.length} entries, expected ${count}`);
      return array;
    },
  };
}

function grid(read: Reader, valuesName: string): SurfaceArrays {
  const cells = read.rows * read.columns;
  const mask = read.take("missing_value_mask", cells);
  if (!(mask instanceof Uint8Array)) throw new WireError("missing_value_mask must be uint8");
  return {
    longitude: read.take("longitude", read.columns),
    latitude: read.take("latitude", read.rows),
    values: read.take(valuesName, cells),
    missingValueMask: mask,
  };
}

export function decodeSlice(descriptor: SliceDescriptor, buffer: ArrayBuffer): SurfaceArrays {
  return grid(reader(descriptor, SLICE_WIRE_FORMAT, buffer), "values");
}

export function decodeVector(descriptor: VectorDescriptor, buffer: ArrayBuffer): VectorArrays {
  const read = reader(descriptor, VECTOR_WIRE_FORMAT, buffer);
  const cells = read.rows * read.columns;
  return { ...grid(read, "speed"), eastward: read.take("eastward", cells), northward: read.take("northward", cells) };
}
