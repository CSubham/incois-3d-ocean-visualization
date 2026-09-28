"""Storage: the object store, and the catalogue when one is reachable."""

import numpy as np
import pytest
import xarray as xr

from ingestion.domain.package import (
    CanonicalPackage, CoordinateSet, DatasetGeometry, SourceInfo, VariableSpec,
)
from ingestion.domain.selection import ImportSelection
from ingestion.domain.validation import ValidationResult
from ingestion.storage.objects import LocalObjectStore, ObjectStoreError
from ingestion.storage.postgres import (
    _catalogue_coordinate_values, _extent_of, _profiles_in, _signed,
)
from ingestion.tests.query_support import model_package


def _profiles(rows: int = 6) -> xr.Dataset:
    return xr.Dataset(
        {"TEMP": (("observation",), np.full(rows, 27.0), {"units": "degC"})},
        coords={
            "time": ("observation",
                     np.array(["2024-09-01"] * rows, dtype="datetime64[ns]")),
            "latitude": ("observation", np.linspace(5, 15, rows)),
            "longitude": ("observation", np.linspace(70, 80, rows)),
            "PRES": ("observation", np.linspace(0, 500, rows)),
            "PLATFORM_NUMBER": ("observation",
                                np.array(["2902203"] * 3 + ["1902671"] * 3)),
            "CYCLE_NUMBER": ("observation", np.array([1, 1, 1, 2, 2, 2])),
        })


def _package(dataset: xr.Dataset, geometry: DatasetGeometry) -> CanonicalPackage:
    return CanonicalPackage(
        import_id="test123", dataset=dataset, geometry=geometry,
        variables=(VariableSpec(name="TEMP", original_name="TEMP",
                                units="degC"),),
        coordinates=CoordinateSet(time="time", vertical="PRES",
                                  latitude="latitude", longitude="longitude"),
        source=SourceInfo(source_id="s", source_name="S", dataset_id="d",
                          dataset_name="D", kind="remote"),
        selection=ImportSelection(source_id="s", dataset_id="d"),
        validation=ValidationResult(checks_run=("a",)))


# -- the object store --------------------------------------------------------

def test_an_array_is_written_and_read_back(tmp_path):
    store = LocalObjectStore(tmp_path)
    dataset = xr.Dataset({"t": (("x",), np.arange(3.0), {"units": "degC"})})
    reference = store.put("abc", dataset)
    assert store.exists(reference)
    assert list(store.open(reference)["t"].values) == [0.0, 1.0, 2.0]


def test_a_stored_array_cannot_be_overwritten(tmp_path):
    """A repeat import is a new version, never an edit to an old one."""
    store = LocalObjectStore(tmp_path)
    dataset = xr.Dataset({"t": (("x",), np.arange(3.0))})
    store.put("abc", dataset)
    with pytest.raises(ObjectStoreError, match="immutable"):
        store.put("abc", dataset)


def test_a_reference_cannot_escape_the_store(tmp_path):
    with pytest.raises(ObjectStoreError, match="outside the store"):
        LocalObjectStore(tmp_path).open("../../etc/passwd")


def test_a_missing_reference_is_reported(tmp_path):
    with pytest.raises(ObjectStoreError, match="not in the store"):
        LocalObjectStore(tmp_path).open("nothing.nc")


# -- what the catalogue derives ---------------------------------------------

def test_model_coordinate_values_are_captured_exactly_for_the_catalogue():
    values = _catalogue_coordinate_values(model_package())

    assert values == {
        "time_values": ["2026-09-28T00:00:00.000000000"],
        "depth_values": [0.0, 10.0, 20.0],
    }


def test_observation_coordinate_rows_remain_in_the_managed_object():
    values = _catalogue_coordinate_values(
        _package(_profiles(), DatasetGeometry.PROFILE))

    assert values == {"time_values": None, "depth_values": None}

def test_the_extent_covers_what_was_stored():
    extent = _extent_of(_package(_profiles(), DatasetGeometry.PROFILE))
    assert extent["depth_min"] == 0.0
    assert extent["depth_max"] == 500.0
    assert extent["time_start"].year == 2024
    assert "POLYGON((70.0 5.0" in extent["footprint"]


def test_rows_are_grouped_into_the_casts_they_came_from():
    """Two floats, one cycle each, so two profiles -- not six rows."""
    profiles = _profiles_in(_package(_profiles(), DatasetGeometry.PROFILE))
    assert len(profiles) == 2
    assert {p["platform_id"] for p in profiles} == {"2902203", "1902671"}
    assert all(p["measurements"] == 3 for p in profiles)


def test_without_an_identifier_rows_are_one_profile_not_invented_ones():
    dataset = _profiles().drop_vars(["PLATFORM_NUMBER", "CYCLE_NUMBER"])
    profiles = _profiles_in(_package(dataset, DatasetGeometry.PROFILE))
    assert len(profiles) == 1
    assert profiles[0]["measurements"] == 6


def test_longitudes_are_stored_signed_whatever_the_source_used():
    """A model on a 0-360 axis must still be findable at -60."""
    assert _signed(300.0) == -60.0
    assert _signed(75.0) == 75.0


def test_a_gridded_field_has_no_instruments_to_record():
    grid = xr.Dataset(
        {"t": (("lat", "lon"), np.zeros((2, 2)), {"units": "degC"})},
        coords={"lat": [1.0, 2.0], "lon": [70.0, 71.0]})
    package = CanonicalPackage(
        import_id="g", dataset=grid, geometry=DatasetGeometry.GRID,
        variables=(VariableSpec(name="t", original_name="t", units="degC"),),
        coordinates=CoordinateSet(latitude="lat", longitude="lon"),
        source=SourceInfo(source_id="s", source_name="S", dataset_id="d",
                          dataset_name="D", kind="remote"),
        selection=ImportSelection(source_id="s", dataset_id="d"),
        validation=ValidationResult(checks_run=("a",)))
    extent = _extent_of(package)
    assert extent["footprint"]          # a field still has a footprint
    assert "depth_min" not in extent    # but no depth, and no profiles
