"""Wire format for a scalar point-field product.

Two parts, fetched separately. A JSON descriptor travels on the control path;
one binary buffer travels on the data path. The descriptor states where every
array sits in the buffer -- name, dtype, count, offset, length -- so a client
views the bytes directly instead of guessing layout from sizes. All arrays are
little-endian and start on an eight-byte boundary, so a browser can take a
typed-array view without copying.

Values keep their source dtype; nothing is quantized for delivery.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping

import numpy as np

from processing import ScalarPointFieldProduct

WIRE_FORMAT = "s5.point-field-wire/1.0"
MEDIA_TYPE = "application/octet-stream"
_ALIGNMENT = 8

#: dtypes every browser can view as a typed array without conversion.
_VIEWABLE = {"f4", "f8", "i1", "i2", "i4", "u1", "u2", "u4"}

#: Order of the components in each ``source_index`` row.
SOURCE_INDEX_COMPONENTS = ("time", "depth", "latitude", "longitude")


class WireFormatError(ValueError):
    """A product cannot be expressed in this wire format without loss."""


def _little_endian(name: str, array: np.ndarray) -> np.ndarray:
    array = np.ascontiguousarray(array)
    code = f"{array.dtype.kind}{array.dtype.itemsize}"
    if code not in _VIEWABLE:
        raise WireFormatError(
            f"{name} has dtype {array.dtype}, which a browser cannot view "
            "without conversion")
    return array.astype(array.dtype.newbyteorder("<"), copy=False)


def _unsigned_32(name: str, values: Any) -> np.ndarray:
    array = np.asarray(values, dtype=np.int64)
    if array.size and (array.min() < 0 or array.max() > np.iinfo(np.uint32).max):
        raise WireFormatError(f"{name} does not fit in 32 bits")
    return array.astype("<u4")


def _arrays(product: ScalarPointFieldProduct) -> list[tuple[str, np.ndarray]]:
    points = product.points
    source_index = np.array(
        [[index.time, index.depth, index.latitude, index.longitude]
         for index in points.source_indices], dtype=np.int64).reshape(-1)
    return [
        ("longitude", _little_endian("longitude", points.longitude)),
        ("latitude", _little_endian("latitude", points.latitude)),
        ("depth", _little_endian("depth", points.depth)),
        ("values", _little_endian("values", points.values)),
        ("missing_value_mask",
         np.asarray(points.missing_value_mask, dtype="<u1")),
        ("source_index", _unsigned_32("source_index", source_index)),
        ("selected_subset_flat_index",
         _unsigned_32("selected_subset_flat_index",
                      product.sampling.selected_subset_flat_indices)),
    ]


def encode(product: ScalarPointFieldProduct) -> tuple[list[dict[str, Any]], bytes]:
    """The array layout and the one buffer it describes."""
    layout: list[dict[str, Any]] = []
    parts: list[bytes] = []
    offset = 0
    for name, array in _arrays(product):
        padding = -offset % _ALIGNMENT
        parts.append(b"\0" * padding)
        offset += padding
        data = array.tobytes(order="C")
        entry = {"name": name, "dtype": array.dtype.str, "count": int(array.size),
                 "byte_offset": offset, "byte_length": len(data)}
        if name == "source_index":
            entry["components"] = list(SOURCE_INDEX_COMPONENTS)
        layout.append(entry)
        parts.append(data)
        offset += len(data)
    return layout, b"".join(parts)


def decode(layout: list[Mapping[str, Any]], buffer: bytes) -> dict[str, np.ndarray]:
    """Read a buffer back through its layout, as any client would."""
    return {entry["name"]: np.frombuffer(
                buffer, dtype=np.dtype(entry["dtype"]),
                count=entry["count"], offset=entry["byte_offset"])
            for entry in layout}


def _plain(value: Any) -> Any:
    """JSON-ready form of product metadata. Non-finite floats become null."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, frozenset, set)):
        return [_plain(v) for v in value]
    if isinstance(value, np.datetime64):
        return str(np.datetime_as_string(value, unit="auto"))
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def describe(product: ScalarPointFieldProduct, *,
             data_url: str | None) -> dict[str, Any]:
    """The control-path descriptor: every scientific fact, no bulk arrays."""
    layout, buffer = encode(product)
    metadata = {f.name: _plain(getattr(product, f.name))
                for f in fields(product) if f.name != "points"}
    metadata["sampling"].pop("selected_subset_flat_indices")
    return {
        "wire_format": WIRE_FORMAT,
        "product": metadata,
        "point_count": len(product.points.source_indices),
        "data": {
            "url": data_url,
            "media_type": MEDIA_TYPE,
            "byte_order": "little",
            "byte_length": len(buffer),
            "arrays": layout,
        },
    }
