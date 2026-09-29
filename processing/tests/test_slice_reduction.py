"""Fitting slices to a view's cell budget by a recorded block mean."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from processing import (
    DepthSliceSelection, GeographicBounds, GridValidationError,
    InvalidRequestError, build_depth_slice,
)
from processing.slice_reduction import (
    BLOCK_MEAN, NO_REDUCTION, reduce_depth_slice, reduction_factor,
)
from processing.tests import fixtures


def _slice(values: np.ndarray, latitudes: np.ndarray | None = None):
    """A one-level slice of the given (lat, lon) values; NaN is missing."""
    rows, columns = values.shape
    if latitudes is None:
        latitudes = np.arange(rows, dtype=np.float64)
    dataset = xr.Dataset(
        data_vars={"water_temp": (("time", "depth", "lat", "lon"),
                                  values.reshape(1, 1, rows, columns),
                                  {"units": "degree_Celsius"})},
        coords={
            "time": np.array(["2026-01-01"], dtype="datetime64[ns]"),
            "depth": ("depth", [0.0], {"units": "m", "positive": "down"}),
            "lat": ("lat", latitudes, {"units": "degrees_north"}),
            "lon": ("lon", np.arange(columns, dtype=np.float64) + 60.0,
                    {"units": "degrees_east"}),
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


def test_equal_area_weights_match_the_old_mask_aware_results():
    values = np.array([[1, 3, 10, np.nan],
                       [np.nan, 5, np.nan, np.nan]], dtype=np.float32)
    equal_weight_latitudes = np.array([-60.0, 60.0])
    reduced = reduce_depth_slice(
        _slice(values, equal_weight_latitudes), 2)
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
    reduced = reduce_depth_slice(_slice(edge, equal_weight_latitudes), 2)
    assert list(reduced.data.missing_value_mask[0]) == [False, True]


def test_latitude_weighting_matches_a_hand_computed_conservative_mean():
    values = np.array([[0.0, 0.0], [10.0, 10.0]], dtype=np.float32)
    reduced = reduce_depth_slice(
        _slice(values, np.array([0.0, 60.0])), maximum_cells=1)

    # Two cells at weight cos(0)=1 and two at weight cos(60)=0.5.
    assert reduced.data.values[0, 0] == pytest.approx(10.0 / 3.0)
    assert reduced.reduction.cell_methods == "area: mean"
    assert reduced.reduction.weighting == (
        "cos(latitude) cell-area weights on a regular lat/lon grid")
    assert not reduced.interpolation.is_interpolated


def test_coordinates_are_block_centres_and_ranges_describe_what_is_delivered():
    values = np.arange(30, dtype=np.float32).reshape(5, 6)
    reduced = reduce_depth_slice(_slice(values), 6)   # factor 3 → 2 x 2
    assert reduced.reduction.factor == 3
    assert list(reduced.data.longitude) == [61.0, 64.0]
    assert list(reduced.data.latitude) == [1.0, 3.5]  # the last block holds rows 3-4
    weights = np.cos(np.deg2rad([3.0, 4.0]))
    expected = np.sum(values[3:, 3:] * weights[:, None]) / (3 * weights.sum())
    assert reduced.physical_range.maximum == pytest.approx(expected)
    assert reduced.data.latitude_source_indices == (0, 3)
    assert "clipped" in reduced.reduction.source_index_meaning


def test_float32_means_are_delivered_as_declared_float32():
    reduced = reduce_depth_slice(
        _slice(np.arange(8, dtype=np.float32).reshape(2, 4)), 2)

    assert reduced.data.values.dtype == np.dtype("float32")
    assert reduced.delivered_dtype == "float32"


def test_a_non_positive_budget_is_refused():
    with pytest.raises(InvalidRequestError):
        reduce_depth_slice(_slice(np.ones((2, 2), dtype=np.float32)), 0)


def test_a_non_positive_side_limit_is_refused_instead_of_looping():
    with pytest.raises(InvalidRequestError, match="maximum delivered side"):
        reduction_factor((2, 2), 2, maximum_side=0)


def test_irregular_latitude_spacing_is_refused_for_area_weighting():
    product = _slice(
        np.ones((3, 2), dtype=np.float32),
        np.array([0.0, 10.0, 30.0]),
    )

    with pytest.raises(GridValidationError, match="regular latitude spacing"):
        reduce_depth_slice(product, 1)


def test_axes_stored_with_rounding_are_regular_enough_to_weight():
    """HYCOM stores longitude rounded to ~1e-4 degrees and latitude as
    float32; a regular grid must not be refused for that."""
    from processing.slice_reduction import _regular_axis

    longitude = np.array([30.0, 30.0799560546875, 30.1600341796875,
                          30.239990234375, 30.3199462890625])
    latitude = np.float32(-30.0) + np.float32(0.04) * np.arange(9, dtype=np.float32)
    _regular_axis(longitude, "longitude")
    _regular_axis(latitude.astype(np.float64), "latitude")
    with pytest.raises(Exception, match="regular longitude"):
        _regular_axis(np.array([0.0, 1.0, 3.0]), "longitude")
