"""Self-describing binary wire format for current-vector slices."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

import numpy as np

from processing import DepthSliceProduct, VectorSliceProduct
from serving.wire import plain
from serving.wire_layout import (
    ArrayEntry, MEDIA_TYPE, decode_arrays, little_endian, pack_arrays,
    unsigned_32,
)

WIRE_FORMAT = "s5.vector-slice-wire/1.0"


def _arrays(product: VectorSliceProduct) -> list[ArrayEntry]:
    east, north = product.eastward, product.northward
    shape = list(east.dimensions.slice_shape)
    grid = {"shape": shape, "order": "C"}
    return [
        ("longitude", little_endian("longitude", east.data.longitude),
         {"role": "longitude"}),
        ("latitude", little_endian("latitude", east.data.latitude),
         {"role": "latitude"}),
        ("eastward", little_endian("eastward", east.data.values),
         {"role": "eastward_component", **grid}),
        ("northward", little_endian("northward", north.data.values),
         {"role": "northward_component", **grid}),
        ("speed", little_endian("speed", product.speed),
         {"role": "derived_speed", **grid}),
        ("missing_value_mask", np.asarray(
            product.missing_value_mask, dtype="<u1"),
         {"role": "missing_value_mask", **grid}),
        ("time_source_index", unsigned_32(
            "time_source_index", [east.data.time_source_index]),
         {"role": "source_time_index"}),
        ("depth_source_index", unsigned_32(
            "depth_source_index", east.interpolation.source_depth_indices),
         {"role": "source_depth_index"}),
        ("latitude_source_index", unsigned_32(
            "latitude_source_index", east.data.latitude_source_indices),
         {"role": "source_latitude_index"}),
        ("longitude_source_index", unsigned_32(
            "longitude_source_index", east.data.longitude_source_indices),
         {"role": "source_longitude_index"}),
    ]


def encode(product: VectorSliceProduct
           ) -> tuple[list[dict[str, Any]], bytes]:
    return pack_arrays(_arrays(product))


def decode(layout: list[Mapping[str, Any]], buffer: bytes
           ) -> dict[str, np.ndarray]:
    return decode_arrays(layout, buffer)


def _component(product: DepthSliceProduct) -> dict[str, Any]:
    return {item.name: plain(getattr(product, item.name))
            for item in fields(product) if item.name != "data"}


def describe(product: VectorSliceProduct, *,
             data_url: str | None) -> dict[str, Any]:
    layout, buffer = encode(product)
    return {
        "wire_format": WIRE_FORMAT,
        "product": {
            "schema_version": product.schema_version,
            "product_type": product.product_type,
            "units": product.units,
            "speed_range": plain(product.speed_range),
            "eastward": _component(product.eastward),
            "northward": _component(product.northward),
        },
        "grid_shape": list(product.eastward.dimensions.slice_shape),
        "data": {
            "url": data_url, "media_type": MEDIA_TYPE, "byte_order": "little",
            "byte_length": len(buffer), "arrays": layout,
        },
    }
