"""The delivery format: every array recoverable, nothing converted silently."""

from __future__ import annotations

import json

import numpy as np
import pytest

from processing import LocalExecutor
from processing.tests import fixtures
from serving import wire


def _product(dataset=None, maximum_points: int = 5):
    versions = {fixtures.VERSION: dataset} if dataset is not None else None
    executor = LocalExecutor(fixtures.builder(versions), maximum_points=100,
                             maximum_cells=1000)
    return executor.submit(fixtures.request(maximum_points)).product


def test_every_array_round_trips_exactly_with_its_source_dtype():
    product = _product()
    layout, buffer = wire.encode(product)
    arrays = wire.decode(layout, buffer)

    np.testing.assert_array_equal(arrays["values"], product.points.values)
    assert arrays["values"].dtype == np.dtype("<f4")
    np.testing.assert_array_equal(arrays["longitude"], product.points.longitude)
    np.testing.assert_array_equal(arrays["latitude"], product.points.latitude)
    np.testing.assert_array_equal(arrays["depth"], product.points.depth)
    np.testing.assert_array_equal(arrays["missing_value_mask"].astype(bool),
                                  product.points.missing_value_mask)
    assert tuple(arrays["selected_subset_flat_index"]) == \
        product.sampling.selected_subset_flat_indices


def test_source_indices_are_rows_in_the_declared_component_order():
    product = _product()
    layout, buffer = wire.encode(product)
    rows = wire.decode(layout, buffer)["source_index"].reshape(-1, 4)
    entry = next(e for e in layout if e["name"] == "source_index")

    assert entry["components"] == ["time", "depth", "latitude", "longitude"]
    assert [tuple(row) for row in rows] == [
        (i.time, i.depth, i.latitude, i.longitude)
        for i in product.points.source_indices]


def test_arrays_start_on_eight_byte_boundaries_and_fill_the_buffer():
    layout, buffer = wire.encode(_product(maximum_points=7))

    assert all(entry["byte_offset"] % 8 == 0 for entry in layout)
    last = layout[-1]
    assert last["byte_offset"] + last["byte_length"] == len(buffer)


def test_big_endian_source_values_are_delivered_little_endian_unchanged():
    dataset = fixtures.grid()
    dataset["water_temp"] = dataset["water_temp"].astype(">f4")
    product = _product(dataset)
    layout, buffer = wire.encode(product)

    values = wire.decode(layout, buffer)["values"]
    assert values.dtype == np.dtype("<f4")
    np.testing.assert_array_equal(values, product.points.values)


def test_a_dtype_a_browser_cannot_view_is_refused_rather_than_converted():
    dataset = fixtures.grid()
    dataset["water_temp"] = dataset["water_temp"].astype(np.int64)

    with pytest.raises(wire.WireFormatError, match="int64"):
        wire.encode(_product(dataset))


def test_the_descriptor_is_plain_json_with_every_fact_and_no_bulk_arrays():
    product = _product()
    described = wire.describe(product, data_url="/data")
    text = json.dumps(described, allow_nan=False)
    decoded = json.loads(text)
    meta = decoded["product"]

    assert decoded["wire_format"] == wire.WIRE_FORMAT
    assert decoded["point_count"] == 5
    assert decoded["data"]["url"] == "/data"
    assert meta["identity"]["dataset_version_id"] == fixtures.VERSION
    assert meta["identity"]["time_value"].startswith("2026-01-02")
    assert meta["spatial_reference"] == {"crs": "EPSG:4326",
                                         "vertical_positive": "down"}
    assert meta["coordinate_transform"]["kind"] == "identity"
    assert meta["mask_semantics"]["true_means"]
    assert meta["sampling"]["original_point_count"] == 12
    assert "selected_subset_flat_indices" not in meta["sampling"]
    assert "points" not in meta
