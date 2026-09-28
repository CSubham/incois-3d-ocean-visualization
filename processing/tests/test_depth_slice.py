"""Exact and explicitly interpolated depth-slice products."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from processing import (
    AllMissingSubsetError, DepthSelectionError, DepthSliceSelection,
    GeographicBounds, GridValidationError, WorkLimitError, build_depth_slice,
)
from processing.tests import fixtures


def _selection(depth=10.0, interpolation="none") -> DepthSliceSelection:
    return DepthSliceSelection(
        variable="water_temp",
        time=np.datetime64("2026-01-02T00:00:00", "ns"),
        area=GeographicBounds(
            west=65.0, east=90.0, south=-1.0, north=10.0),
        depth=depth,
        interpolation=interpolation,
    )


def test_exact_depth_slice_preserves_source_cells_indices_and_mask():
    dataset = fixtures.grid()
    dataset["water_temp"].values[1, 1, 1, 2] = np.nan

    product = build_depth_slice(
        dataset, fixtures.descriptor(), _selection())

    np.testing.assert_array_equal(product.data.longitude, [70.0, 80.0, 90.0])
    np.testing.assert_array_equal(product.data.latitude, [0.0, 10.0])
    np.testing.assert_array_equal(
        product.data.values,
        dataset.water_temp.values[1, 1, 1:3, 1:4],
    )
    assert product.data.missing_value_mask.tolist() == [
        [False, True, False], [False, False, False]]
    assert product.data.time_source_index == 1
    assert product.data.latitude_source_indices == (1, 2)
    assert product.data.longitude_source_indices == (1, 2, 3)
    assert product.interpolation.source_depth_indices == (1,)
    assert product.interpolation.weights == (1.0,)
    assert product.interpolation.is_interpolated is False
    assert product.source_dtype == "float32"
    assert product.delivered_dtype == "float32"


def test_non_source_depth_is_not_silently_interpolated():
    with pytest.raises(DepthSelectionError, match="request 'linear'"):
        build_depth_slice(
            fixtures.grid(), fixtures.descriptor(), _selection(depth=5.0))


def test_explicit_linear_interpolation_records_levels_weights_and_dtype():
    dataset = fixtures.grid()

    product = build_depth_slice(
        dataset, fixtures.descriptor(),
        _selection(depth=5.0, interpolation="linear"),
    )

    expected = (dataset.water_temp.values[1, 0, 1:3, 1:4]
                + dataset.water_temp.values[1, 1, 1:3, 1:4]) / 2.0
    np.testing.assert_array_equal(product.data.values, expected)
    assert product.interpolation.source_depth_indices == (0, 1)
    assert product.interpolation.source_depth_values == (0.0, 10.0)
    assert product.interpolation.weights == (0.5, 0.5)
    assert product.interpolation.is_interpolated is True
    assert product.coordinate_transform.kind == "linear-depth-interpolation"
    assert product.source_dtype == "float32"
    assert product.delivered_dtype == "float64"


def test_linear_interpolation_masks_a_cell_if_either_source_is_missing():
    dataset = fixtures.grid()
    dataset["water_temp"].values[1, 0, 1, 1] = np.nan

    product = build_depth_slice(
        dataset, fixtures.descriptor(),
        _selection(depth=5.0, interpolation="linear"),
    )

    assert product.data.missing_value_mask[0, 0]
    assert product.physical_range.valid_point_count == 5
    assert product.physical_range.missing_point_count == 1


def test_descending_depth_coordinates_select_the_same_physical_slice():
    ascending = fixtures.grid()
    descending = ascending.sortby("depth", ascending=False)

    product = build_depth_slice(
        descending, fixtures.descriptor(),
        _selection(depth=5.0, interpolation="linear"),
    )

    expected = (ascending.water_temp.values[1, 0, 1:3, 1:4]
                + ascending.water_temp.values[1, 1, 1:3, 1:4]) / 2.0
    np.testing.assert_array_equal(product.data.values, expected)
    assert product.interpolation.source_depth_indices == (2, 1)
    assert product.interpolation.source_depth_values == (0.0, 10.0)


def test_slice_rejects_non_monotonic_depth_and_extrapolation():
    dataset = fixtures.grid().assign_coords(depth=(
        "depth", [0.0, 20.0, 10.0], {"units": "m", "positive": "down"}))
    with pytest.raises(GridValidationError, match="strictly ascending"):
        build_depth_slice(dataset, fixtures.descriptor(), _selection())

    with pytest.raises(DepthSelectionError, match="never extrapolates"):
        build_depth_slice(
            fixtures.grid(), fixtures.descriptor(),
            _selection(depth=30.0, interpolation="linear"),
        )


def test_slice_enforces_work_limit_and_does_not_mutate_input():
    dataset = fixtures.grid()
    original = dataset.copy(deep=True)

    with pytest.raises(WorkLimitError):
        build_depth_slice(
            dataset, fixtures.descriptor(), _selection(), maximum_cells=5)
    xr.testing.assert_identical(dataset, original)


def test_all_missing_slice_is_a_typed_failure():
    dataset = fixtures.grid()
    dataset["water_temp"].values[1, 1, 1:3, 1:4] = np.nan

    with pytest.raises(AllMissingSubsetError, match="all 6 cells"):
        build_depth_slice(dataset, fixtures.descriptor(), _selection())
