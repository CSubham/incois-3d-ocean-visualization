"""Self-describing binary wire format for scientific depth slices."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

import numpy as np

from processing import DepthSliceProduct
from serving.wire import plain
from serving.wire_layout import (
    ArrayEntry, MEDIA_TYPE, decode_arrays, little_endian, pack_arrays,
    unsigned_32,
)


WIRE_FORMAT = "s5.depth-slice-wire/1.0"


def _arrays(product: DepthSliceProduct) -> list[ArrayEntry]:
    shape = list(product.dimensions.slice_shape)
    return [
        ("longitude", little_endian("longitude", product.data.longitude),
         {"role": "longitude"}),
        ("latitude", little_endian("latitude", product.data.latitude),
         {"role": "latitude"}),
        ("values", little_endian("values", product.data.values),
         {"role": "measurement", "shape": shape, "order": "C"}),
        ("missing_value_mask", np.asarray(
            product.data.missing_value_mask, dtype="<u1"),
         {"role": "missing_value_mask", "shape": shape, "order": "C"}),
        ("time_source_index", unsigned_32(
            "time_source_index", [product.data.time_source_index]),
         {"role": "source_time_index"}),
        ("depth_source_index", unsigned_32(
            "depth_source_index",
            product.interpolation.source_depth_indices),
         {"role": "source_depth_index"}),
        ("latitude_source_index", unsigned_32(
            "latitude_source_index",
            product.data.latitude_source_indices),
         {"role": "source_latitude_index"}),
        ("longitude_source_index", unsigned_32(
            "longitude_source_index",
            product.data.longitude_source_indices),
         {"role": "source_longitude_index"}),
    ]


def encode(product: DepthSliceProduct
           ) -> tuple[list[dict[str, Any]], bytes]:
    """Return the declared array layout and its aligned binary buffer."""
    return pack_arrays(_arrays(product))


def decode(layout: list[Mapping[str, Any]], buffer: bytes
           ) -> dict[str, np.ndarray]:
    """Read slice arrays back through their declared layout."""
    return decode_arrays(layout, buffer)


def describe(product: DepthSliceProduct, *,
             data_url: str | None) -> dict[str, Any]:
    """Return JSON-ready scientific metadata without duplicating bulk data."""
    layout, buffer = encode(product)
    metadata = {item.name: plain(getattr(product, item.name))
                for item in fields(product) if item.name != "data"}
    return {
        "wire_format": WIRE_FORMAT,
        "product": metadata,
        "grid_shape": list(product.dimensions.slice_shape),
        "data": {
            "url": data_url,
            "media_type": MEDIA_TYPE,
            "byte_order": "little",
            "byte_length": len(buffer),
            "arrays": layout,
        },
    }
