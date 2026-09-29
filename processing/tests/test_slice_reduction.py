"""Fitting slices to a view's cell budget by a recorded block mean."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from processing import (
    DepthSliceSelection, GeographicBounds, InvalidRequestError, build_depth_slice,
)
from processing.slice_reduction import (
    BLOCK_MEAN, NO_REDUCTION, reduce_depth_slice, reduction_factor,
)
from processing.tests import fixtures


def _slice(values: np.ndarray):
    """A one-level slice of the given (lat, lon) values; NaN is missing."""
    rows, columns = values.shape
    dataset = xr.Dataset(
        data_vars={"water_temp": (("time", "depth", "lat", "lon"),
                                  values.reshape(1, 1, rows, columns),
                                  {"units": "degree_Celsius"})},
        coords={
            "time": np.array(["2026-01-01"], dtype="datetime64[ns]"),
            "depth": ("depth", [0.0], {"units": "m", "positive": "down"}),
            "lat": ("lat", np.arange(rows, dtype=np.float64), {"units": "degrees_north"}),
            "lon": ("lon", np.arange(columns, dtype=np.float64) + 60.0, {"units": "degrees_east"}),
        },
    )
    return build_depth_slice(dataset, fixtures.descriptor(), DepthSliceSelection(
        variable="water_temp", time=dataset["time"].values[0],
        area=GeographicBounds(west=-180, east=180, south=-90, north=90), depth=0.0))


def test_the_factor_is_the_smallest_square_block_that_fits():
    assert reduction_factor((100, 100), 10_000) == 1
    assert reduction_factor((100, 100), 2_500) == 2
    assert reduction_factor((101, 100), 2_500) == 3          # 51 x 50 > 2500
    assert reduction_factor((4251, 4500), 2_000_000) == 4    # a 1/12-degree globe
    assert reduction_factor((10, 9000), 1_000_000, maximum_side=4096) == 3


def test_a_slice_within_budget_is_delivered_unchanged_and_says_so():
    product = _slice(np.arange(12, dtype=np.float32).reshape(3, 4))
    reduced = reduce_depth_slice(product, 100)
    assert reduced.reduction.method == NO_REDUCTION and reduced.reduction.factor == 1
    assert np.array_equal(reduced.data.values, product.data.values)


def test_block_means_ignore_missing_cells_and_keep_all_missing_blocks_missing():
    values = np.array([[1, 3, 10, np.nan],
                       [np.nan, 5, np.nan, np.nan]], dtype=np.float32)
    reduced = reduce_depth_slice(_slice(values), 2)
    assert reduced.reduction.method == BLOCK_MEAN and reduced.reduction.factor == 2
    assert reduced.reduction.source_shape == (2, 4)
    assert reduced.dimensions.slice_shape == (1, 2)
    # (1 + 3 + 5) / 3 valid cells: land never pulls the mean toward zero.
    assert reduced.data.values[0, 0] == pytest.approx(3.0)
    assert reduced.data.values[0, 1] == pytest.approx(10.0)
    assert not reduced.data.missing_value_mask.any()

    land = np.full((2, 2), np.nan, dtype=np.float32)
    land[0, 0] = 4.0
    edge = np.hstack([land, np.full((2, 2), np.nan, dtype=np.float32)])
    reduced = reduce_depth_slice(_slice(edge), 2)
    assert list(reduced.data.missing_value_mask[0]) == [False, True]


def test_coordinates_are_block_centres_and_ranges_describe_what_is_delivered():
    values = np.arange(30, dtype=np.float32).reshape(5, 6)
    reduced = reduce_depth_slice(_slice(values), 6)   # factor 3 → 2 x 2
    assert reduced.reduction.factor == 3
    assert list(reduced.data.longitude) == [61.0, 64.0]
    assert list(reduced.data.latitude) == [1.0, 3.5]  # the last block holds rows 3-4
    assert reduced.physical_range.maximum == pytest.approx(values[3:, 3:].mean())
    assert reduced.data.latitude_source_indices == (0, 3)


def test_a_non_positive_budget_is_refused():
    with pytest.raises(InvalidRequestError):
        reduce_depth_slice(_slice(np.ones((2, 2), dtype=np.float32)), 0)
