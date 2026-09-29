"""Longitude selection by angle, in either convention."""

from __future__ import annotations

import numpy as np
import pytest

from processing import EmptySubsetError, GeographicBounds, InvalidRequestError
from processing.subsetter import _longitude_indices

axis360 = np.arange(0.0, 360.0, 10.0)        # 0..350, HYCOM-like
axis180 = np.arange(-180.0, 180.0, 10.0)     # -180..170


def test_signed_bounds_select_the_same_cells_from_a_0_360_axis():
    indices, delivered = _longitude_indices(axis360, -70.0, -50.0, "lon")
    assert list(axis360[indices]) == [290.0, 300.0, 310.0]
    assert list(delivered) == [290.0, 300.0, 310.0]   # source values, unchanged


def test_crossing_the_source_seam_continues_longitudes_past_it():
    indices, delivered = _longitude_indices(axis360, -20.0, 20.0, "lon")
    assert list(axis360[indices]) == [340.0, 350.0, 0.0, 10.0, 20.0]
    assert list(delivered) == [340.0, 350.0, 360.0, 370.0, 380.0]
    assert np.all(np.diff(delivered) > 0)


def test_crossing_the_antimeridian_on_a_signed_axis():
    indices, delivered = _longitude_indices(axis180, 160.0, 200.0, "lon")
    assert list(axis180[indices]) == [160.0, 170.0, -180.0, -170.0, -160.0]
    assert list(delivered) == [160.0, 170.0, 180.0, 190.0, 200.0]


def test_a_whole_globe_request_keeps_source_order_and_values():
    indices, delivered = _longitude_indices(axis360, -180.0, 180.0, "lon")
    assert list(indices) == list(range(axis360.size))
    assert np.array_equal(delivered, axis360)


def test_a_near_whole_extent_from_a_signed_catalogue_takes_every_cell():
    # A catalogue reports a 0..360 grid's extent as -179.92..180 (signed).
    axis = np.arange(0.0, 360.0, 0.08)
    indices, delivered = _longitude_indices(axis, -179.92, 180.0, "lon")
    assert indices.size == axis.size
    assert np.all(np.diff(delivered) > 0)


def test_nothing_selected_is_an_empty_subset():
    with pytest.raises(EmptySubsetError):
        _longitude_indices(np.array([10.0, 20.0]), 30.0, 40.0, "lon")


def test_bounds_may_not_span_more_than_a_full_turn():
    with pytest.raises(InvalidRequestError):
        GeographicBounds(west=-180, east=200, south=0, north=1)
