// Decoder for the S5 observation-marker wire format
// (serving/wire_observation.py). Text columns (identities, timestamps) arrive
// as UTF-8 bytes plus n+1 offsets; numeric columns are typed-array views.

import { view, WireError, type ArrayLayout } from "./wire";

export const OBSERVATION_WIRE_FORMAT = "s5.observation-wire/1.0";

export interface TextColumnLayout extends ArrayLayout {
  text_column?: string;
  component?: "offsets" | "utf8";
}

export interface MarkerDescriptor {
  wire_format: string;
  observation_count: number;
  product: {
    product_type: string;
    dataset_identity: { dataset_id: string; dataset_version_id: string };
    coordinates: {
      units: Record<string, string | null>;
      vertical_kind: "depth" | "pressure";
    };
    spatial_reference: { crs: string; vertical_positive: "down" | "up" };
    grouping: { delivered_marker_count: number; original_observation_count: number };
    skipped_profiles: unknown[];
  };
  data: { url: string; byte_length: number; arrays: TextColumnLayout[] };
}

/** One layer's markers, index-aligned across every column. */
export interface MarkerSet {
  datasetVersionId: string;
  verticalKind: "depth" | "pressure";
  verticalUnits: string | null;
  longitude: Float64Array;
  latitude: Float64Array;
  verticalMinimum: Float64Array;
  verticalMaximum: Float64Array;
  platformIds: string[];
  cycles: string[];
  observedAt: string[];
}

function numeric(layouts: Map<string, TextColumnLayout>, buffer: ArrayBuffer, name: string): Float64Array {
  const layout = layouts.get(name);
  if (!layout) throw new WireError(`the marker data has no ${name} array`);
  const array = view(layout, buffer);
  if (!(array instanceof Float64Array)) throw new WireError(`${name} must be float64`);
  return array;
}

function text(arrays: TextColumnLayout[], buffer: ArrayBuffer, column: string): string[] {
  const part = (component: "offsets" | "utf8") =>
    arrays.find((a) => a.text_column === column && a.component === component);
  const offsetsLayout = part("offsets");
  const bytesLayout = part("utf8");
  if (!offsetsLayout || !bytesLayout) throw new WireError(`the marker data has no ${column} text column`);
  const offsets = view(offsetsLayout, buffer);
  const bytes = view(bytesLayout, buffer);
  if (!(offsets instanceof Uint32Array) || !(bytes instanceof Uint8Array)) {
    throw new WireError(`${column} must be uint32 offsets over uint8 bytes`);
  }
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const values: string[] = [];
  for (let i = 0; i + 1 < offsets.length; i++) {
    if (offsets[i + 1] < offsets[i] || offsets[i + 1] > bytes.length) {
      throw new WireError(`${column} offsets are out of range`);
    }
    values.push(decoder.decode(bytes.subarray(offsets[i], offsets[i + 1])));
  }
  return values;
}

export function decodeMarkers(descriptor: MarkerDescriptor, buffer: ArrayBuffer): MarkerSet {
  if (descriptor.wire_format !== OBSERVATION_WIRE_FORMAT) {
    throw new WireError(`unsupported wire format ${descriptor.wire_format}`);
  }
  if (buffer.byteLength !== descriptor.data.byte_length) {
    throw new WireError(`expected ${descriptor.data.byte_length} bytes, received ${buffer.byteLength}`);
  }
  const arrays = descriptor.data.arrays;
  const byName = new Map(arrays.map((a) => [a.name, a]));
  const set: MarkerSet = {
    datasetVersionId: descriptor.product.dataset_identity.dataset_version_id,
    verticalKind: descriptor.product.coordinates.vertical_kind,
    verticalUnits: descriptor.product.coordinates.units.vertical ?? null,
    longitude: numeric(byName, buffer, "longitude"),
    latitude: numeric(byName, buffer, "latitude"),
    verticalMinimum: numeric(byName, buffer, "vertical_minimum"),
    verticalMaximum: numeric(byName, buffer, "vertical_maximum"),
    platformIds: text(arrays, buffer, "platform_id"),
    cycles: text(arrays, buffer, "cycle"),
    observedAt: text(arrays, buffer, "time"),
  };
  const count = descriptor.product.grouping.delivered_marker_count;
  const columns = [set.longitude, set.latitude, set.verticalMinimum, set.verticalMaximum,
    set.platformIds, set.cycles, set.observedAt];
  if (columns.some((column) => column.length !== count)) {
    throw new WireError(`marker columns do not all hold ${count} markers`);
  }
  return set;
}
