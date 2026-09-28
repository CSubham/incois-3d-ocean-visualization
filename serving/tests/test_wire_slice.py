"""Golden depth-slice wire layout and scientific metadata."""

from __future__ import annotations

import json

import numpy as np

from processing import DepthSliceSelection, GeographicBounds, build_depth_slice
from processing.tests import fixtures
from serving import wire_slice


def _product(depth=10.0, interpolation="none"):
    return build_depth_slice(
        fixtures.grid(),
        fixtures.descriptor(),
        DepthSliceSelection(
            variable="water_temp",
            time=np.datetime64("2026-01-02T00:00:00", "ns"),
            area=GeographicBounds(
                west=65.0, east=90.0, south=-1.0, north=10.0),
            depth=depth,
            interpolation=interpolation,
        ),
    )


def test_golden_exact_slice_arrays_round_trip_with_declared_shape():
    product = _product()
    layout, buffer = wire_slice.encode(product)
    arrays = wire_slice.decode(layout, buffer)

    np.testing.assert_array_equal(arrays["longitude"], product.data.longitude)
    np.testing.assert_array_equal(arrays["latitude"], product.data.latitude)
    np.testing.assert_array_equal(
        arrays["values"].reshape(product.dimensions.slice_shape),
        product.data.values,
    )
    assert arrays["values"].dtype == np.dtype("<f4")
    assert arrays["time_source_index"].tolist() == [1]
    assert arrays["depth_source_index"].tolist() == [1]
    assert arrays["latitude_source_index"].tolist() == [1, 2]
    assert arrays["longitude_source_index"].tolist() == [1, 2, 3]
    values = next(item for item in layout if item["name"] == "values")
    assert values["shape"] == [2, 3]
    assert values["order"] == "C"
    assert all(item["byte_offset"] % 8 == 0 for item in layout)
    last = layout[-1]
    assert last["byte_offset"] + last["byte_length"] == len(buffer)


def test_linear_slice_wire_records_transformation_without_quantization():
    product = _product(depth=5.0, interpolation="linear")
    layout, buffer = wire_slice.encode(product)
    arrays = wire_slice.decode(layout, buffer)
    described = wire_slice.describe(product, data_url="/slices/one/data")
    decoded = json.loads(json.dumps(described, allow_nan=False))

    assert arrays["values"].dtype == np.dtype("<f8")
    assert arrays["depth_source_index"].tolist() == [0, 1]
    assert decoded["wire_format"] == wire_slice.WIRE_FORMAT
    assert decoded["grid_shape"] == [2, 3]
    assert decoded["product"]["interpolation"] == {
        "policy": "linear",
        "requested_depth": 5.0,
        "delivered_depth": 5.0,
        "source_depth_indices": [0, 1],
        "source_depth_values": [0.0, 10.0],
        "weights": [0.5, 0.5],
        "is_interpolated": True,
    }
    assert decoded["product"]["source_dtype"] == "float32"
    assert decoded["product"]["delivered_dtype"] == "float64"
    assert decoded["data"]["url"] == "/slices/one/data"
    assert "data" not in decoded["product"]
