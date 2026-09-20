"""OPeNDAP model adapter, exercised without touching the network."""

import numpy as np
import pytest
import xarray as xr

from ingestion.adapters.opendap import (
    OpendapAdapter, _as_instant, _as_number, _longitudes_for, _subset,
    _values_in,
)
from ingestion.config import HYCOM
from ingestion.domain.errors import SelectionError
from ingestion.domain.selection import Area, DepthRange, ImportSelection

HOURS = "hours since 2000-01-01 00:00:00"


def _axis(values):
    return xr.DataArray(np.array(values, dtype=float), dims="lon")


def _selection(**kwargs):
    return ImportSelection(source_id="hycom_opendap",
                           dataset_id="GLBy0.08_expt_93.0", **kwargs)


# -- longitude conventions ---------------------------------------------------

def test_a_negative_longitude_is_converted_onto_a_0_to_360_axis():
    """Models differ. -60 means nothing on a 0-360 axis until it is 300."""
    axis = _axis(np.arange(0, 360, 0.08))
    assert _longitudes_for(axis, -60, -40) == (300.0, 320.0)


def test_a_longitude_over_180_is_converted_onto_a_signed_axis():
    axis = _axis(np.arange(-180, 180, 0.25))
    assert _longitudes_for(axis, 300, 320) == (-60.0, -40.0)


def test_a_longitude_already_in_the_axis_convention_is_left_alone():
    axis = _axis(np.arange(0, 360, 0.08))
    assert _longitudes_for(axis, 70, 80) == (70.0, 80.0)


def test_crossing_the_edge_of_the_range_is_named_not_silently_wrong():
    axis = _axis(np.arange(0, 360, 0.08))
    with pytest.raises(SelectionError, match="crossing the edge"):
        _longitudes_for(axis, 350, 10)


# -- time in the model's own numbering ---------------------------------------

def test_a_model_time_value_is_rendered_as_an_instant():
    assert _as_instant(165900.0, HOURS).startswith("2018-12-04")


def test_a_date_is_expressed_in_the_model_numbering():
    assert _as_number("2018-12-04T12:00:00Z", HOURS) == 165900.0


def test_a_round_trip_through_both_holds():
    original = 200000.0
    assert _as_number(_as_instant(original, HOURS), HOURS) == original


def test_an_unparseable_date_is_refused():
    with pytest.raises(SelectionError, match="not a valid date"):
        _as_number("last Tuesday", HOURS)


def test_a_non_calendar_time_unit_is_left_as_a_number():
    """HYCOM's `tau` carries "hours since analysis", which is not a calendar."""
    assert _as_instant(6.0, "hours since analysis") == 6.0


# -- size, before anything is transferred ------------------------------------

def _grid() -> xr.Dataset:
    return xr.Dataset(
        {"water_temp": (("time", "depth", "lat", "lon"),
                        np.zeros((2, 4, 10, 20)), {"units": "degC"})},
        coords={"time": np.array([0.0, 3.0]), "depth": [0.0, 10, 50, 100],
                "lat": np.linspace(-10, 10, 10),
                "lon": np.linspace(60, 90, 20)})


def test_the_size_is_known_before_any_transfer():
    assert _values_in(_grid()) == 2 * 4 * 10 * 20


def test_subsetting_reduces_what_would_be_transferred():
    whole = _grid()
    part, applied = _subset(whole, _selection(depth=DepthRange(0, 50),
                                              area=Area(70, 80, -5, 5)))
    assert _values_in(part) < _values_in(whole)
    assert "depth" in applied and "area" in applied


def test_an_empty_selection_is_reported_rather_than_returned():
    with pytest.raises(SelectionError, match="no .* values fall inside"):
        _subset(_grid(), _selection(depth=DepthRange(900, 1000)))


# -- the source itself -------------------------------------------------------

def test_hycom_is_configured_as_a_curated_set_not_a_catalogue():
    """A THREDDS catalogue lists everything a centre publishes."""
    adapter = OpendapAdapter(HYCOM)
    listed = adapter.list_datasets()
    assert len(listed) == len(HYCOM.datasets)
    assert all(ref.dataset_id for ref in listed)


def test_an_unlisted_dataset_is_refused():
    from ingestion.domain.errors import SourceError
    with pytest.raises(SourceError, match="not offered"):
        OpendapAdapter(HYCOM)._entry("something_else")


def test_the_adapter_declares_what_it_can_narrow():
    capabilities = OpendapAdapter(HYCOM).describe().capabilities
    assert capabilities.variable_selection
    assert capabilities.time_subsetting
    assert capabilities.depth_subsetting
    assert capabilities.spatial_subsetting
