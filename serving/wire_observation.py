"""Self-describing binary wire format for observation products.

Numeric arrays retain their source dtype, become little-endian, and begin on
eight-byte boundaries as in :mod:`serving.wire`. Text identities, QC flags and
timestamps use UTF-8 bytes plus unsigned offset arrays; the layout declares the
encoding, so clients never infer string boundaries or coerce flags to numbers.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping

import numpy as np

from processing import (
    ObservationMarkerProduct, ObservationProfileProduct,
)
from serving.wire import MEDIA_TYPE, WireFormatError


WIRE_FORMAT = "s5.observation-wire/1.0"
_ALIGNMENT = 8
_VIEWABLE = {"f4", "f8", "i1", "i2", "i4", "u1", "u2", "u4"}

ObservationProduct = ObservationMarkerProduct | ObservationProfileProduct
ArrayEntry = tuple[str, np.ndarray, dict[str, Any]]


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


def _text(value: Any) -> str:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return ""
        return str(np.datetime_as_string(value, unit="auto"))
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WireFormatError("text data is not valid UTF-8") from exc
    return str(value)


def _text_entries(name: str, values: list[Any], *, role: str,
                  missing_mask: np.ndarray | None = None,
                  **metadata: Any) -> list[ArrayEntry]:
    if missing_mask is None:
        missing = np.zeros(len(values), dtype=bool)
    else:
        missing = np.asarray(missing_mask, dtype=bool)
        if missing.shape != (len(values),):
            raise WireFormatError(f"{name} text mask does not align")
    encoded = [b"" if missing[index] else _text(value).encode("utf-8")
               for index, value in enumerate(values)]
    offsets = [0]
    for value in encoded:
        offsets.append(offsets[-1] + len(value))
    payload = np.frombuffer(b"".join(encoded), dtype=np.uint8).copy()
    common = {"text_column": name, "encoding": "utf-8-offsets", "role": role,
              **metadata}
    return [
        (f"{name}_offsets", _unsigned_32(f"{name}_offsets", offsets),
         {**common, "component": "offsets", "value_count": len(values)}),
        (f"{name}_utf8", payload,
         {**common, "component": "utf8", "value_count": len(values)}),
    ]


def _marker_arrays(product: ObservationMarkerProduct) -> list[ArrayEntry]:
    markers = product.markers
    arrays: list[ArrayEntry] = [
        ("longitude", _little_endian(
            "longitude", np.asarray([marker.longitude for marker in markers])),
         {"role": "longitude"}),
        ("latitude", _little_endian(
            "latitude", np.asarray([marker.latitude for marker in markers])),
         {"role": "latitude"}),
        ("vertical_minimum", _little_endian(
            "vertical_minimum", np.asarray(
                [marker.vertical_range.minimum for marker in markers])),
         {"role": "vertical_range_minimum"}),
        ("vertical_maximum", _little_endian(
            "vertical_maximum", np.asarray(
                [marker.vertical_range.maximum for marker in markers])),
         {"role": "vertical_range_maximum"}),
        ("vertical_valid_count", _unsigned_32(
            "vertical_valid_count",
            [marker.vertical_range.valid_observation_count for marker in markers]),
         {"role": "vertical_valid_observation_count"}),
        ("vertical_missing_count", _unsigned_32(
            "vertical_missing_count", [
                marker.vertical_range.missing_observation_count
                for marker in markers]),
         {"role": "vertical_missing_observation_count"}),
        ("representative_source_index", _unsigned_32(
            "representative_source_index",
            [marker.representative_source_index for marker in markers]),
         {"role": "representative_source_index"}),
    ]
    arrays += _text_entries(
        "platform_id", [marker.identity.platform_id for marker in markers],
        role="platform_identity")
    arrays += _text_entries(
        "cycle", [marker.identity.cycle for marker in markers],
        role="cycle_profile_identity")
    arrays += _text_entries(
        "time", [marker.time_value for marker in markers], role="timestamp",
        source_dtype=product.coordinates.dtypes["time"])

    offsets = [0]
    flattened: list[int] = []
    for marker in markers:
        flattened.extend(marker.source_indices)
        offsets.append(len(flattened))
    arrays += [
        ("marker_source_index_offsets", _unsigned_32(
            "marker_source_index_offsets", offsets),
         {"role": "marker_source_index_offsets", "value_count": len(markers)}),
        ("marker_source_index", _unsigned_32(
            "marker_source_index", flattened),
         {"role": "source_observation_index"}),
    ]
    return arrays


def _profile_arrays(product: ObservationProfileProduct) -> list[ArrayEntry]:
    arrays: list[ArrayEntry] = [
        ("vertical", _little_endian("vertical", product.vertical_values),
         {"role": "vertical"}),
        ("vertical_missing_value_mask", np.asarray(
            product.vertical_missing_value_mask, dtype="<u1"),
         {"role": "missing_value_mask", "for": "vertical"}),
        ("timestamp_missing_value_mask", np.asarray(
            product.timestamp_missing_value_mask, dtype="<u1"),
         {"role": "missing_value_mask", "for": "timestamp"}),
        ("source_index", _unsigned_32(
            "source_index", product.source_indices),
         {"role": "source_observation_index"}),
    ]
    arrays += _text_entries(
        "timestamp", list(product.timestamps), role="timestamp",
        missing_mask=product.timestamp_missing_value_mask,
        source_dtype=product.coordinates.dtypes["time"])

    for position, variable in enumerate(product.variables):
        prefix = f"variable_{position}"
        arrays += [
            (f"{prefix}_values", _little_endian(
                f"{prefix}_values", variable.values),
             {"role": "measurement", "variable": variable.name}),
            (f"{prefix}_missing_value_mask", np.asarray(
                variable.missing_value_mask, dtype="<u1"),
             {"role": "missing_value_mask", "variable": variable.name}),
        ]
        if variable.qc_flags is not None:
            arrays += _text_entries(
                f"{prefix}_qc", list(variable.qc_flags), role="quality_flag",
                missing_mask=variable.qc_missing_value_mask,
                variable=variable.name, qc_variable=variable.qc_variable,
                source_dtype=variable.qc_source_dtype)
            arrays.append((
                f"{prefix}_qc_missing_value_mask",
                np.asarray(variable.qc_missing_value_mask, dtype="<u1"),
                {"role": "missing_value_mask", "variable": variable.name,
                 "for": "quality_flag"},
            ))
    return arrays


def _arrays(product: ObservationProduct) -> list[ArrayEntry]:
    if isinstance(product, ObservationMarkerProduct):
        return _marker_arrays(product)
    if isinstance(product, ObservationProfileProduct):
        return _profile_arrays(product)
    raise TypeError(f"unsupported observation product {type(product).__name__}")


def encode(product: ObservationProduct) -> tuple[list[dict[str, Any]], bytes]:
    """Return the declared array layout and its one binary buffer."""
    layout: list[dict[str, Any]] = []
    parts: list[bytes] = []
    offset = 0
    for name, array, metadata in _arrays(product):
        padding = -offset % _ALIGNMENT
        parts.append(b"\0" * padding)
        offset += padding
        data = np.ascontiguousarray(array).tobytes(order="C")
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


def decode(layout: list[Mapping[str, Any]], buffer: bytes
           ) -> dict[str, np.ndarray]:
    """Read numeric layout entries back without interpreting their roles."""
    return {entry["name"]: np.frombuffer(
                buffer, dtype=np.dtype(entry["dtype"]),
                count=entry["count"], offset=entry["byte_offset"])
            for entry in layout}


def decode_text(layout: list[Mapping[str, Any]], buffer: bytes,
                name: str) -> tuple[str, ...]:
    """Decode one explicitly named UTF-8 offset column."""
    arrays = decode(layout, buffer)
    try:
        offsets = arrays[f"{name}_offsets"]
        payload = arrays[f"{name}_utf8"].tobytes()
    except KeyError as exc:
        raise WireFormatError(f"no text column {name!r} is in the layout") from exc
    return tuple(payload[int(start):int(end)].decode("utf-8")
                 for start, end in zip(offsets[:-1], offsets[1:]))


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name))
                for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, frozenset, set)):
        return [_plain(child) for child in value]
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else _text(value)
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def _metadata(product: ObservationProduct) -> dict[str, Any]:
    if isinstance(product, ObservationMarkerProduct):
        return {item.name: _plain(getattr(product, item.name))
                for item in fields(product) if item.name != "markers"}
    excluded = {
        "source_indices", "vertical_values", "vertical_missing_value_mask",
        "timestamps", "timestamp_missing_value_mask", "variables",
    }
    metadata = {item.name: _plain(getattr(product, item.name))
                for item in fields(product) if item.name not in excluded}
    metadata["variables"] = [
        {item.name: _plain(getattr(variable, item.name))
         for item in fields(variable)
         if item.name not in {"values", "missing_value_mask", "qc_flags",
                              "qc_missing_value_mask"}}
        for variable in product.variables
    ]
    return metadata


def describe(product: ObservationProduct, *,
             data_url: str | None) -> dict[str, Any]:
    """JSON-ready scientific metadata plus an explicit binary layout."""
    layout, buffer = encode(product)
    count = (len(product.markers)
             if isinstance(product, ObservationMarkerProduct)
             else len(product.source_indices))
    return {
        "wire_format": WIRE_FORMAT,
        "product": _metadata(product),
        "observation_count": count,
        "data": {
            "url": data_url,
            "media_type": MEDIA_TYPE,
            "byte_order": "little",
            "byte_length": len(buffer),
            "arrays": layout,
        },
    }
