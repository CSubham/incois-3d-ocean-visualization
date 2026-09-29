// Decoder for the S5 observation-marker wire format
// (serving/wire_observation.py). Text columns (identities, timestamps) arrive
// as UTF-8 bytes plus n+1 offsets; numeric columns are typed-array views.
import { view, WireError } from "./wire";
export const OBSERVATION_WIRE_FORMAT = "s5.observation-wire/1.0";
const REAL_DTYPES = new Set(["<f4", "<f8"]);
function numeric(layouts, buffer, name) {
    const layout = layouts.get(name);
    if (!layout)
        throw new WireError(`the marker data has no ${name} array`);
    if (!REAL_DTYPES.has(layout.dtype)) {
        throw new WireError(`${name} has dtype ${layout.dtype}; marker coordinates must be floating point`);
    }
    return view(layout, buffer);
}
function text(arrays, buffer, column) {
    const part = (component) => arrays.find((a) => a.text_column === column && a.component === component);
    const offsetsLayout = part("offsets");
    const bytesLayout = part("utf8");
    if (!offsetsLayout || !bytesLayout)
        throw new WireError(`the marker data has no ${column} text column`);
    const offsets = view(offsetsLayout, buffer);
    const bytes = view(bytesLayout, buffer);
    if (!(offsets instanceof Uint32Array) || !(bytes instanceof Uint8Array)) {
        throw new WireError(`${column} must be uint32 offsets over uint8 bytes`);
    }
    const decoder = new TextDecoder("utf-8", { fatal: true });
    const values = [];
    for (let i = 0; i + 1 < offsets.length; i++) {
        if (offsets[i + 1] < offsets[i] || offsets[i + 1] > bytes.length) {
            throw new WireError(`${column} offsets are out of range`);
        }
        values.push(decoder.decode(bytes.subarray(offsets[i], offsets[i + 1])));
    }
    return values;
}
export function decodeMarkers(descriptor, buffer) {
    if (descriptor.wire_format !== OBSERVATION_WIRE_FORMAT) {
        throw new WireError(`unsupported wire format ${descriptor.wire_format}`);
    }
    if (buffer.byteLength !== descriptor.data.byte_length) {
        throw new WireError(`expected ${descriptor.data.byte_length} bytes, received ${buffer.byteLength}`);
    }
    const arrays = descriptor.data.arrays;
    const byName = new Map(arrays.map((a) => [a.name, a]));
    const set = {
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
function mask(layouts, buffer, name) {
    const layout = layouts.get(name);
    if (!layout)
        throw new WireError(`the profile data has no ${name} array`);
    const array = view(layout, buffer);
    if (!(array instanceof Uint8Array))
        throw new WireError(`${name} must be uint8`);
    return array;
}
/** CF flag_values with a space-separated flag_meanings, as a lookup by flag text. */
function flagMeanings(meta) {
    if (!meta.qc_flag_values || !meta.qc_flag_meanings)
        return null;
    const meanings = meta.qc_flag_meanings.trim().split(/\s+/);
    if (meanings.length !== meta.qc_flag_values.length)
        return null;
    return new Map(meta.qc_flag_values.map((value, i) => [String(value), meanings[i].replace(/_/g, " ")]));
}
export function decodeProfile(descriptor, buffer) {
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
    if (!vertical)
        throw new WireError("the profile data has no vertical array");
    const timestampMissing = mask(byName, buffer, "timestamp_missing_value_mask");
    const timestamps = text(arrays, buffer, "timestamp").map((t, i) => (timestampMissing[i] ? null : t));
    const variables = product.variables.map((meta, i) => {
        const prefix = `variable_${i}`;
        const values = byName.get(`${prefix}_values`);
        if (!values)
            throw new WireError(`the profile data has no values for ${meta.name}`);
        let qcFlags = null;
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
    const decoded = {
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
