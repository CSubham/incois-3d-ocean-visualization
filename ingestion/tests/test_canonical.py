"""Coordinate identification, geometry classification and convention checks."""

import numpy as np
import pytest
import xarray as xr

from ingestion.canonical import (
    ancillary_names, classify_geometry, describe_variables,
    identify_coordinates,
)
from ingestion.conventions import validate
from ingestion.domain.errors import ConventionError
from ingestion.domain.package import DatasetGeometry


def _grid() -> xr.Dataset:
    return xr.Dataset(
        {"temp": (("time", "depth", "lat", "lon"),
                  np.ones((1, 2, 3, 4)), {"units": "degC"})},
        coords={"time": np.array(["2024-01-01"], dtype="datetime64[ns]"),
                "depth": [0.0, 10.0], "lat": [1.0, 2.0, 3.0],
                "lon": [4.0, 5.0, 6.0, 7.0]})


def _rows(count: int, moving: bool, *, marker: str | None = None,
          vertical: bool = True) -> xr.Dataset:
    coords = {
        "time": ("observation",
                 np.array(["2024-01-01"] * count, dtype="datetime64[ns]")),
        "lat": ("observation",
                np.linspace(1, 9, count) if moving else np.ones(count)),
        "lon": ("observation",
                np.linspace(1, 9, count) if moving else np.full(count, 2.0)),
    }
    if vertical:
        coords["depth"] = ("observation", np.linspace(0, 100, count))
    if marker:
        coords[marker] = ("observation", np.arange(count))
    return xr.Dataset(
        {"temp": (("observation",), np.ones(count), {"units": "degC"})},
        coords=coords)


def test_coordinates_are_identified_by_role():
    found = identify_coordinates(_grid())
    assert found.identified() == {
        "time": "time", "vertical": "depth",
        "latitude": "lat", "longitude": "lon"}


def test_gridded_data_is_classified_as_a_grid():
    dataset = _grid()
    assert classify_geometry(dataset, identify_coordinates(dataset)) \
        is DatasetGeometry.GRID


def test_declared_feature_type_is_taken_at_its_word():
    dataset = _rows(5, moving=True)
    dataset.attrs["featureType"] = "profile"
    assert classify_geometry(dataset, identify_coordinates(dataset)) \
        is DatasetGeometry.PROFILE


def test_unsupported_feature_type_is_reported_not_guessed():
    dataset = _grid()
    dataset.attrs["featureType"] = "swath"
    with pytest.raises(ConventionError, match="featureType"):
        classify_geometry(dataset, identify_coordinates(dataset))


def test_a_moving_platform_with_depth_is_a_trajectory_profile():
    dataset = _rows(5, moving=True, marker="trajectory")
    assert classify_geometry(dataset, identify_coordinates(dataset)) \
        is DatasetGeometry.TRAJECTORY_PROFILE


def test_grouped_casts_are_profiles():
    dataset = _rows(5, moving=True, marker="profile_id")
    assert classify_geometry(dataset, identify_coordinates(dataset)) \
        is DatasetGeometry.PROFILE


def test_a_moving_platform_without_depth_is_a_trajectory():
    dataset = _rows(5, moving=True, vertical=False)
    assert classify_geometry(dataset, identify_coordinates(dataset)) \
        is DatasetGeometry.TRAJECTORY


def test_missing_position_cannot_be_classified():
    dataset = xr.Dataset({"temp": (("n",), np.ones(3), {"units": "degC"})})
    with pytest.raises(ConventionError, match="latitude and longitude"):
        classify_geometry(dataset, identify_coordinates(dataset))


def test_flags_and_containers_are_not_scientific_variables():
    dataset = _grid()
    dataset["temp_qc"] = (("time", "depth", "lat", "lon"),
                          np.ones((1, 2, 3, 4)))
    dataset["crs"] = ((), 0.0)
    dataset["temp"].attrs["grid_mapping"] = "crs"

    ancillary = ancillary_names(dataset)
    assert "temp_qc" in ancillary and "crs" in ancillary

    names = [spec.name for spec
             in describe_variables(dataset, identify_coordinates(dataset))]
    assert names == ["temp"]


def test_units_are_required_because_values_cannot_be_read_without_them():
    dataset = _grid()
    del dataset["temp"].attrs["units"]
    coordinates = identify_coordinates(dataset)
    result = validate(dataset, coordinates, DatasetGeometry.GRID,
                      describe_variables(dataset, coordinates))
    assert not result.passed
    assert any(issue.check == "units_declared" for issue in result.issues)


def test_a_sound_dataset_passes_every_check():
    dataset = _grid()
    coordinates = identify_coordinates(dataset)
    result = validate(dataset, coordinates, DatasetGeometry.GRID,
                      describe_variables(dataset, coordinates))
    assert result.passed, result.summary()
    assert "geometry_classified" in result.checks_run


def test_an_unclassifiable_dataset_fails_validation():
    dataset = _grid()
    coordinates = identify_coordinates(dataset)
    result = validate(dataset, coordinates, None,
                      describe_variables(dataset, coordinates),
                      "shape could not be determined")
    assert not result.passed
    assert any(i.check == "geometry_classified" for i in result.issues)
