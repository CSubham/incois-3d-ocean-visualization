// Decoder for the S5 point-field wire format (serving/wire.py).
//
// The descriptor states each array's dtype, count and byte offset; arrays are
// little-endian and eight-byte aligned, so each becomes a typed-array view on
// the one buffer without copying. Nothing is inferred from sizes.
export const WIRE_FORMAT = "s5.point-field-wire/1.0";
export class WireError extends Error {
}
const VIEWS = {
    "<f4": Float32Array, "<f8": Float64Array,
    "|i1": Int8Array, "<i2": Int16Array, "<i4": Int32Array,
    "|u1": Uint8Array, "<u2": Uint16Array, "<u4": Uint32Array,
};
export function view(layout, buffer) {
    const View = VIEWS[layout.dtype];
    if (!View)
        throw new WireError(`${layout.name} has unsupported dtype ${layout.dtype}`);
    if (layout.byte_offset + layout.byte_length > buffer.byteLength) {
        throw new WireError(`${layout.name} extends past the end of the data`);
    }
    return new View(buffer, layout.byte_offset, layout.count);
}
export function decodePointField(descriptor, buffer) {
    if (descriptor.wire_format !== WIRE_FORMAT) {
        throw new WireError(`unsupported wire format ${descriptor.wire_format}`);
    }
    if (buffer.byteLength !== descriptor.data.byte_length) {
        throw new WireError(`expected ${descriptor.data.byte_length} bytes, received ${buffer.byteLength}`);
    }
    const byName = new Map(descriptor.data.arrays.map((a) => [a.name, a]));
    const take = (name) => {
        const layout = byName.get(name);
        if (!layout)
            throw new WireError(`the data has no ${name} array`);
        const array = view(layout, buffer);
        if (array.length !== descriptor.point_count) {
            throw new WireError(`${name} has ${array.length} entries, expected ${descriptor.point_count}`);
        }
        return array;
    };
    const mask = take("missing_value_mask");
    if (!(mask instanceof Uint8Array))
        throw new WireError("missing_value_mask must be uint8");
    return {
        longitude: take("longitude"),
        latitude: take("latitude"),
        depth: take("depth"),
        values: take("values"),
        missingValueMask: mask,
    };
}
