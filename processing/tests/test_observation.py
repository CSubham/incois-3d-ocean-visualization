"""Scientific observation marker and exact-profile products."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import xarray as xr

from processing import (
    AllMissingObservationError, ObservationIdentityError,
    ObservationProfileIdentity, ObservationProfileSelection,
    ObservationValidationError, ObservationVariableError,
    build_observation_markers, build_observation_profile,
)
from processing.tests import observation_fixtures as fixtures


def test_argo_markers_keep_exact_identities_ranges_and_source_rows():
    product = build_observation_markers(
        fixtures.argo(), fixtures.argo_descriptor())

    assert [marker.identity for marker in product.markers] == [
        ObservationProfileIdentity("5901", "7"),
        ObservationProfileIdentity("5902", "8"),
    ]
    first, second = product.markers
    assert first.source_indices == (0, 1, 2, 3)
    assert first.representative_source_index == 0
    assert first.longitude == np.float32(70.0)
    assert first.vertical_range.minimum == np.float32(0.0)
    assert first.vertical_range.maximum == np.float32(20.0)
    assert first.vertical_range.valid_observation_count == 3
    assert first.vertical_range.missing_observation_count == 1
    assert second.representative_source_index == 5
    assert second.longitude == np.float32(82.1)
    assert product.grouping.original_observation_count == 7
    assert product.grouping.delivered_marker_count == 2
    assert "no coordinate averaging" in product.grouping.representative_policy


def test_argo_pressure_metadata_is_not_relabelled_as_depth_in_metres():
    product = build_observation_markers(
        fixtures.argo(), fixtures.argo_descriptor())

    assert product.coordinates.vertical_kind == "pressure"
    assert product.coordinates.units["vertical"] == "dbar"
    assert product.spatial_reference.vertical_positive == "down"
    assert product.spatial_reference.crs == "EPSG:4326"
    assert product.coordinate_transform.kind == "identity"


def test_glider_depth_shape_and_positive_direction_are_explicit():
    descriptor = fixtures.glider_descriptor(positive="up")
    product = build_observation_profile(
        fixtures.glider(), descriptor, fixtures.glider_selection())

    assert product.profile_identity == ObservationProfileIdentity("ru29", "12")
    assert product.coordinates.sample_dimension == "row"
    assert product.coordinates.vertical_kind == "depth"
    assert product.coordinates.units["vertical"] == "m"
    assert product.spatial_reference.vertical_positive == "up"
    np.testing.assert_array_equal(product.vertical_values,
                                  [0.0, 15.0, 30.0, 45.0])


def test_profile_preserves_source_order_values_units_qc_and_timestamps():
    dataset = fixtures.argo()
    product = build_observation_profile(
        dataset, fixtures.argo_descriptor(), fixtures.argo_selection())

    assert product.source_indices == (0, 1, 2, 3)
    np.testing.assert_array_equal(product.vertical_values,
                                  dataset.PRES.values[:4])
    np.testing.assert_array_equal(product.timestamps,
                                  dataset.JULD.values[:4])
    assert product.timestamp_missing_value_mask.tolist() == [False, False,
                                                              True, False]
    temperature, salinity = product.variables
    assert temperature.name == "TEMP"
    assert temperature.units == "degree_Celsius"
    assert temperature.source_dtype == "float32"
    assert temperature.missing_value_mask.tolist() == [False, True,
                                                        False, False]
    assert temperature.qc_variable == "TEMP_QC"
    assert temperature.qc_flags[:2].tolist() == ["1", "4"]
    assert np.isnan(temperature.qc_flags[2])
    assert temperature.qc_flags[3] == "2"
    assert temperature.qc_missing_value_mask.tolist() == [False, False,
                                                           True, False]
    assert salinity.name == "PSAL" and salinity.units == "1e-3"


def test_profile_values_and_coordinates_are_exact_source_rows():
    dataset = fixtures.glider()
    product = build_observation_profile(
        dataset, fixtures.glider_descriptor(), fixtures.glider_selection())
    variable = product.variables[0]

    for output_index, source_index in enumerate(product.source_indices):
        assert product.vertical_values[output_index] == \
            dataset.depth.values[source_index]
        assert product.timestamps[output_index] == dataset.time.values[source_index]
        output = variable.values[output_index]
        source = dataset.temperature.values[source_index]
        assert (np.isnan(output) and np.isnan(source)) or output == source


def test_missing_identity_is_a_typed_marker_failure():
    dataset = fixtures.argo()
    dataset = dataset.assign_coords(
        PLATFORM_NUMBER=("observation", np.array(
            [None, "5901", "5901", "5901", "5902", "5902", "5902"],
            dtype=object)))

    with pytest.raises(ObservationIdentityError, match="source observation 0"):
        build_observation_markers(dataset, fixtures.argo_descriptor())


def test_unknown_exact_identity_is_a_typed_profile_failure():
    selection = ObservationProfileSelection(
        ObservationProfileIdentity("5901", "999"), ("TEMP",))

    with pytest.raises(ObservationIdentityError, match="no observations match"):
        build_observation_profile(
            fixtures.argo(), fixtures.argo_descriptor(), selection)


def test_missing_requested_variable_is_actionable():
    selection = replace(fixtures.argo_selection(), variables=("CHLA",))

    with pytest.raises(ObservationVariableError, match="available variables"):
        build_observation_profile(
            fixtures.argo(), fixtures.argo_descriptor(), selection)


def test_ambiguous_non_row_variable_shape_is_rejected():
    dataset = fixtures.argo()
    dataset["TEMP"] = (("observation", "duplicate"),
                       np.ones((7, 2), dtype=np.float32),
                       {"units": "degree_Celsius"})

    with pytest.raises(ObservationValidationError, match="sample dimension"):
        build_observation_profile(
            dataset, fixtures.argo_descriptor(), fixtures.argo_selection("TEMP"))


def test_a_profile_with_only_missing_requested_values_is_rejected():
    dataset = fixtures.argo()
    dataset["TEMP"].values[:4] = np.nan

    with pytest.raises(AllMissingObservationError, match="no valid values"):
        build_observation_profile(
            dataset, fixtures.argo_descriptor(), fixtures.argo_selection("TEMP"))


def test_marker_requires_an_existing_complete_position_and_time_row():
    dataset = fixtures.argo()
    dataset["LONGITUDE"].values[:4] = np.nan

    with pytest.raises(ObservationValidationError, match="no source row"):
        build_observation_markers(dataset, fixtures.argo_descriptor())


def test_builders_do_not_mutate_the_decoded_dataset():
    dataset = fixtures.argo()
    original = dataset.copy(deep=True)

    build_observation_markers(dataset, fixtures.argo_descriptor())
    build_observation_profile(
        dataset, fixtures.argo_descriptor(), fixtures.argo_selection())

    xr.testing.assert_identical(dataset, original)


def test_product_arrays_are_read_only_snapshots():
    product = build_observation_profile(
        fixtures.argo(), fixtures.argo_descriptor(), fixtures.argo_selection())

    with pytest.raises(ValueError, match="read-only"):
        product.variables[0].values[0] = 99.0
