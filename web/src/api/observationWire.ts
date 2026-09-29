// Decoder for the S5 observation-marker wire format
// (serving/wire_observation.py). Text columns (identities, timestamps) arrive
// as UTF-8 bytes plus n+1 offsets; numeric columns are typed-array views.

import { view, WireError, type ArrayLayout, type NumericArray } from "./wire";

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

/** One layer's markers, index-aligned across every column.
 *
 *  Numeric columns keep the dtype S5 declared: source dtypes are preserved,
 *  so Argo positions may arrive as float32. Nothing is widened or narrowed. */
export interface MarkerSet {
  datasetVersionId: string;
  /** The markers' coordinate reference; a renderer refuses one it cannot place. */
  crs: string;
  verticalKind: "depth" | "pressure";
  verticalUnits: string | null;
  longitude: NumericArray;
  latitude: NumericArray;
  verticalMinimum: NumericArray;
  verticalMaximum: NumericArray;
  platformIds: string[];
  cycles: string[];
  observedAt: string[];
}

const REAL_DTYPES = new Set(["<f4", "<f8"]);

function numeric(layouts: Map<string, TextColumnLayout>, buffer: ArrayBuffer, name: string): NumericArray {
  const layout = layouts.get(name);
  if (!layout) throw new WireError(`the marker data has no ${name} array`);
  if (!REAL_DTYPES.has(layout.dtype)) {
    throw new WireError(`${name} has dtype ${layout.dtype}; marker coordinates must be floating point`);
  }
  return view(layout, buffer);
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
    crs: descriptor.product.spatial_reference.crs,
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

export interface ProfileVariableMeta {
  name: string;
  units: string | null;
  qc_variable: string | null;
  qc_flag_values: (number | string)[] | null;
  qc_flag_meanings: string | null;
  qc_conventions: string | null;
}

export interface ProfileDescriptor {
  wire_format: string;
  observation_count: number;
  product: {
    product_type: string;
    dataset_identity: { dataset_id: string; dataset_version_id: string };
    profile_identity: { platform_id: string; cycle: string };
    coordinates: { units: Record<string, string | null>; vertical_kind: "depth" | "pressure" };
    spatial_reference: { crs: string; vertical_positive: "down" | "up" };
    variables: ProfileVariableMeta[];
  };
  data: { url: string; byte_length: number; arrays: TextColumnLayout[] };
}

export interface ProfileVariable {
  name: string;
  units: string | null;
  values: NumericArray;
  missing: Uint8Array;
  /** QC flag per level as the source wrote it, or null when none is declared. */
  qcFlags: (string | null)[] | null;
  /** Declared meaning of each flag value (CF flag_values/flag_meanings), or null when absent. */
  qcMeanings: Map<string, string> | null;
  qcConventions: string | null;
}

/** One exact profile: levels in source order, pressure kept as pressure. */
export interface DecodedProfile {
  datasetVersionId: string;
  platformId: string;
  cycle: string;
  verticalKind: "depth" | "pressure";
  verticalUnits: string | null;
  verticalPositive: "down" | "up";
  vertical: NumericArray;
  verticalMissing: Uint8Array;
  timestamps: (string | null)[];
  variables: ProfileVariable[];
}

function mask(layouts: Map<string, TextColumnLayout>, buffer: ArrayBuffer, name: string): Uint8Array {
  const layout = layouts.get(name);
  if (!layout) throw new WireError(`the profile data has no ${name} array`);
  const array = view(layout, buffer);
  if (!(array instanceof Uint8Array)) throw new WireError(`${name} must be uint8`);
  return array;
}

/** CF flag_values with a space-separated flag_meanings, as a lookup by flag text. */
function flagMeanings(meta: ProfileVariableMeta): Map<string, string> | null {
  if (!meta.qc_flag_values || !meta.qc_flag_meanings) return null;
  const meanings = meta.qc_flag_meanings.trim().split(/\s+/);
  if (meanings.length !== meta.qc_flag_values.length) return null;
  return new Map(meta.qc_flag_values.map((value, i) => [String(value), meanings[i].replace(/_/g, " ")]));
}

export function decodeProfile(descriptor: ProfileDescriptor, buffer: ArrayBuffer): DecodedProfile {
  if (descriptor.wire_format !== OBSERVATION_WIRE_FORMAT) {
    throw new WireError(`unsupported wire format ${descriptor.wire_format}`);
  }
  if (buffer.byteLength !== descriptor.data.byte_length) {
    throw new WireError(`expected ${descriptor.data.byte_length} bytes, received ${buffer.byteLength}`);
  }
  const arrays = descriptor.data.arrays;
  const byName = new Map(arrays.map((a) => [a.name, a]));
  const levels = descriptor.observation_count;
  const product = descriptor.product;
  const vertical = byName.get("vertical");
  if (!vertical) throw new WireError("the profile data has no vertical array");
  const timestampMissing = mask(byName, buffer, "timestamp_missing_value_mask");
  const timestamps = text(arrays, buffer, "timestamp").map((t, i) => (timestampMissing[i] ? null : t));

  const variables = product.variables.map((meta, i) => {
    const prefix = `variable_${i}`;
    const values = byName.get(`${prefix}_values`);
    if (!values) throw new WireError(`the profile data has no values for ${meta.name}`);
    let qcFlags: (string | null)[] | null = null;
    if (meta.qc_variable) {
      const qcMissing = mask(byName, buffer, `${prefix}_qc_missing_value_mask`);
      qcFlags = text(arrays, buffer, `${prefix}_qc`).map((flag, level) => (qcMissing[level] ? null : flag));
    }
    return {
      name: meta.name,
      units: meta.units,
      values: view(values, buffer),
      missing: mask(byName, buffer, `${prefix}_missing_value_mask`),
      qcFlags,
      qcMeanings: flagMeanings(meta),
      qcConventions: meta.qc_conventions,
    };
  });

  const decoded: DecodedProfile = {
    datasetVersionId: product.dataset_identity.dataset_version_id,
    platformId: product.profile_identity.platform_id,
    cycle: product.profile_identity.cycle,
    verticalKind: product.coordinates.vertical_kind,
    verticalUnits: product.coordinates.units.vertical ?? null,
    verticalPositive: product.spatial_reference.vertical_positive,
    vertical: view(vertical, buffer),
    verticalMissing: mask(byName, buffer, "vertical_missing_value_mask"),
    timestamps,
    variables,
  };
  const columns = [decoded.vertical, decoded.verticalMissing, decoded.timestamps,
    ...variables.flatMap((v) => [v.values, v.missing, ...(v.qcFlags ? [v.qcFlags] : [])])];
  if (columns.some((column) => column.length !== levels)) {
    throw new WireError(`profile columns do not all hold ${levels} levels`);
  }
  return decoded;
}
