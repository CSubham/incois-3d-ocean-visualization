"""Golden current-vector wire indices and reduction metadata."""

from __future__ import annotations

import numpy as np

from processing import (
    DepthSliceSelection, GeographicBounds, build_depth_slice,
    build_vector_slice,
)
from processing.slice_reduction import reduce_depth_slice
from processing.tests import fixtures
from serving import wire_vector


def _product():
    dataset = fixtures.grid()
    dims = dataset["water_temp"].dims
    dataset["water_u"] = (dims, np.full(dataset["water_temp"].shape, 3.0,
                                         dtype=np.float32), {"units": "m/s"})
    dataset["water_v"] = (dims, np.full(dataset["water_temp"].shape, 4.0,
                                         dtype=np.float32), {"units": "m/s"})

    def component(variable):
        product = build_depth_slice(
            dataset,
            fixtures.descriptor(),
            DepthSliceSelection(
                variable=variable,
                time=np.datetime64("2026-01-02T00:00:00", "ns"),
                area=GeographicBounds(
                    west=65.0, east=90.0, south=-1.0, north=10.0),
                depth=10.0,
            ),
        )
        return reduce_depth_slice(product, maximum_cells=2)

    return build_vector_slice(component("water_u"), component("water_v"))


def test_vector_wire_carries_horizontal_source_indices_and_reduction():
    product = _product()
    layout, buffer = wire_vector.encode(product)
    arrays = wire_vector.decode(layout, buffer)
    described = wire_vector.describe(product, data_url="/vectors/one/data")

    assert arrays["latitude_source_index"].tolist() == [1]
    assert arrays["longitude_source_index"].tolist() == [1, 3]
    latitude = next(
        item for item in layout if item["name"] == "latitude_source_index")
    longitude = next(
        item for item in layout if item["name"] == "longitude_source_index")
    assert latitude["role"] == "source_latitude_index"
    assert longitude["role"] == "source_longitude_index"
    assert described["product"]["eastward"]["reduction"]["factor"] == 2
    assert described["product"]["northward"]["reduction"]["factor"] == 2
