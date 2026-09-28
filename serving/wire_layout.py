"""Shared, lossless byte-layout primitives for scientific wire products."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np


MEDIA_TYPE = "application/octet-stream"
ALIGNMENT = 8

# Dtypes every browser can view as a typed array without conversion.
VIEWABLE_DTYPES = {"f4", "f8", "i1", "i2", "i4", "u1", "u2", "u4"}

ArrayEntry = tuple[str, np.ndarray, Mapping[str, Any]]


class WireFormatError(ValueError):
    """A product cannot be expressed in a wire format without loss."""


def little_endian(name: str, array: np.ndarray) -> np.ndarray:
    """Return a contiguous viewable array without changing its values."""
    array = np.ascontiguousarray(array)
    code = f"{array.dtype.kind}{array.dtype.itemsize}"
    if code not in VIEWABLE_DTYPES:
        raise WireFormatError(
            f"{name} has dtype {array.dtype}, which a browser cannot view "
            "without conversion")
    return array.astype(array.dtype.newbyteorder("<"), copy=False)


def unsigned_32(name: str, values: Any) -> np.ndarray:
    """Encode non-negative integer indices without silent overflow."""
    array = np.asarray(values, dtype=np.int64)
    if array.size and (array.min() < 0 or array.max() > np.iinfo(np.uint32).max):
        raise WireFormatError(f"{name} does not fit in 32 bits")
    return array.astype("<u4")


def pack_arrays(arrays: Iterable[ArrayEntry]
                ) -> tuple[list[dict[str, Any]], bytes]:
    """Pack declared arrays into one aligned binary buffer."""
    layout: list[dict[str, Any]] = []
    parts: list[bytes] = []
    offset = 0
    for name, source, metadata in arrays:
        array = np.ascontiguousarray(source)
        padding = -offset % ALIGNMENT
        parts.append(b"\0" * padding)
        offset += padding
        data = array.tobytes(order="C")
        layout.append({
            "name": name,
            "dtype": array.dtype.str,
            "count": int(array.size),
            "byte_offset": offset,
            "byte_length": len(data),
            **metadata,
        })
        parts.append(data)
        offset += len(data)
    return layout, b"".join(parts)


def decode_arrays(layout: Iterable[Mapping[str, Any]], buffer: bytes
                  ) -> dict[str, np.ndarray]:
    """Read a buffer back through its declared array layout."""
    return {
        entry["name"]: np.frombuffer(
            buffer,
            dtype=np.dtype(entry["dtype"]),
            count=entry["count"],
            offset=entry["byte_offset"],
        )
        for entry in layout
    }
