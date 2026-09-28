"""Scientific fidelity tests for the sampled scalar point-field path."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import xarray as xr

from processing import (
    IDENTITY_TRANSFORM, MISSING_VALUE_MASK, PRODUCT_SCHEMA_VERSION,
    SAMPLING_POLICY, AllMissingSubsetError, CoordinateRoles,
    DatasetIdentity, DepthBounds, EmptySubsetError, GeographicBounds,
    GridValidationError, InvalidRequestError, PointBudgetError,
    SamplingRequest, ScalarGridDescriptor, ScalarSelection,
    SpatialReference, TimeSelectionError, VariableSelectionError,
    prepare_sampled_scalar_point_field, subset_scalar_field,
)


def _dataset() -> xr.Dataset:
    shape = (2, 3, 3, 4)
    temperature = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    salinity = temperature + np.float32(30.0)
    return xr.Dataset(
        data_vars={
            "water_temp": (
                ("time", "depth", "lat", "lon"), temperature,
                {"units": "degree_Celsius", "standard_name":
                 "sea_water_temperature"},
            ),
            "salinity": (
                ("time", "depth", "lat", "lon"), salinity,
                {"units": "1e-3"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01", "2026-01-02"],
                             dtype="datetime64[ns]"),
            "depth": ("depth", [0.0, 10.0, 20.0], {"units": "m"}),
            "lat": ("lat", [-10.0, 0.0, 10.0],
                    {"units": "degrees_north"}),
            "lon": ("lon", [60.0, 70.0, 80.0, 90.0],
                    {"units": "degrees_east"}),
        },
        attrs={"title": "decoded test grid"},
    )


def _descriptor(provenance: dict | None = None,
                vertical_positive: str = "down") -> ScalarGridDescriptor:
    return ScalarGridDescriptor(
        identity=DatasetIdentity(dataset_id="hycom-glby008",
                                 dataset_version_id="import-123"),
        coordinates=CoordinateRoles(
            time="time", depth="depth", latitude="lat", longitude="lon"),
        spatial_reference=SpatialReference(
            crs="EPSG:4326", vertical_positive=vertical_positive),
        provenance=provenance if provenance is not None else {
            "source": "fixture://decoded-grid",
            "import_id": "import-123",
            "steps": ["decoded", "validated"],
        },
    )


def _selection(variable: str = "water_temp") -> ScalarSelection:
    return ScalarSelection(
        variable=variable,
        time=np.datetime64("2026-01-02T00:00:00", "ns"),
        area=GeographicBounds(west=65.0, east=90.0,
                              south=-1.0, north=10.0),
        depth=DepthBounds(minimum=5.0, maximum=20.0),
    )


def _product(dataset: xr.Dataset | None = None, *, maximum_points: int = 5,
             variable: str = "water_temp"):
    return prepare_sampled_scalar_point_field(
        dataset if dataset is not None else _dataset(),
        _descriptor(), _selection(variable),
        SamplingRequest(maximum_points=maximum_points),
    )


def test_selects_the_requested_scalar_variable_without_a_hard_coded_branch():
    product = _product(variable="salinity")

    assert product.identity.variable == "salinity"
    assert product.variable_units == "1e-3"
    assert np.all(product.points.values >= 30.0)


def test_selects_exactly_one_available_time_and_preserves_its_identity():
    product = _product()

    assert product.identity.time_coordinate == "time"
    assert product.identity.time_value == np.datetime64("2026-01-02", "ns")
    assert {index.time for index in product.points.source_indices} == {1}


def test_latitude_and_longitude_bounds_are_inclusive():
    subset = subset_scalar_field(_dataset(), _descriptor(), _selection())

    np.testing.assert_array_equal(subset.latitude_values, [0.0, 10.0])
    np.testing.assert_array_equal(subset.longitude_values,
                                  [70.0, 80.0, 90.0])
    assert subset.latitude_source_indices == (1, 2)
    assert subset.longitude_source_indices == (1, 2, 3)


def test_depth_range_bounds_are_inclusive():
    subset = subset_scalar_field(_dataset(), _descriptor(), _selection())

    np.testing.assert_array_equal(subset.depth_values, [10.0, 20.0])
    assert subset.depth_source_indices == (1, 2)


def test_ascending_coordinate_order_is_preserved():
    product = _product(maximum_points=100)

    assert product.dimensions.subset_shape == (2, 2, 3)
    np.testing.assert_array_equal(np.unique(product.points.depth), [10.0, 20.0])
    np.testing.assert_array_equal(np.unique(product.points.latitude), [0.0, 10.0])


def test_descending_coordinate_order_and_source_positions_are_preserved():
    descending = _dataset().isel(
        depth=slice(None, None, -1), lat=slice(None, None, -1),
        lon=slice(None, None, -1))
    product = _product(descending, maximum_points=100)

    np.testing.assert_array_equal(product.points.depth[:6],
                                  np.full(6, 20.0))
    np.testing.assert_array_equal(product.points.longitude[:3],
                                  [90.0, 80.0, 70.0])
    assert product.points.source_indices[0].depth == 0
    assert product.points.source_indices[0].latitude == 0
    assert product.points.source_indices[0].longitude == 0


def test_nan_and_masked_source_cells_remain_explicitly_missing():
    dataset = _dataset()
    values = dataset["water_temp"].values.copy()
    values[1, 1, 1, 1] = np.nan
    mask = np.zeros(values.shape, dtype=bool)
    mask[1, 2, 2, 3] = True
    dataset["water_temp"] = xr.DataArray(
        np.ma.array(values, mask=mask),
        dims=("time", "depth", "lat", "lon"),
        attrs={"units": "degree_Celsius"},
    )

    product = _product(dataset, maximum_points=100)

    assert product.points.missing_value_mask.sum() == 2
    assert product.full_subset_range.missing_point_count == 2
    assert np.isnan(product.points.values[0])


def test_identical_requests_produce_identical_products():
    first = _product(maximum_points=7)
    second = _product(maximum_points=7)

    assert first.identity == second.identity
    assert first.sampling == second.sampling
    assert first.points.source_indices == second.points.source_indices
    np.testing.assert_array_equal(first.points.values, second.points.values)
    np.testing.assert_array_equal(first.points.missing_value_mask,
                                  second.points.missing_value_mask)


def test_point_budget_is_enforced_and_sampling_loss_is_explicit():
    product = _product(maximum_points=5)

    assert product.sampling.maximum_points == 5
    assert product.sampling.original_point_count == 12
    assert product.sampling.delivered_point_count == 5
    assert product.sampling.omitted_point_count == 7
    assert product.sampling.is_lossy is True
    assert product.sampling.selected_subset_flat_indices == (0, 2, 5, 8, 11)


def test_budget_above_subset_size_delivers_every_cell_without_loss():
    product = _product(maximum_points=100)

    assert product.sampling.original_point_count == 12
    assert product.sampling.delivered_point_count == 12
    assert product.sampling.omitted_point_count == 0
    assert product.sampling.is_lossy is False


def test_selected_source_indices_trace_every_delivered_value():
    dataset = _dataset()
    product = _product(dataset, maximum_points=5)

    for delivered, source in zip(product.points.values,
                                 product.points.source_indices):
        source_value = dataset["water_temp"].values[
            source.time, source.depth, source.latitude, source.longitude]
        assert delivered == source_value
    assert product.points.source_indices == (
        replace(product.points.source_indices[0],
                time=1, depth=1, latitude=1, longitude=1),
        replace(product.points.source_indices[1],
                time=1, depth=1, latitude=1, longitude=3),
        replace(product.points.source_indices[2],
                time=1, depth=1, latitude=2, longitude=3),
        replace(product.points.source_indices[3],
                time=1, depth=2, latitude=1, longitude=3),
        replace(product.points.source_indices[4],
                time=1, depth=2, latitude=2, longitude=3),
    )


def test_full_subset_and_sample_ranges_are_recorded_separately():
    dataset = _dataset()
    values = dataset["water_temp"].values.copy()
    selected = values[1, 1:, 1:, 1:].copy()
    selected_flat = selected.reshape(-1)
    selected_flat[1] = -999.0
    selected_flat[10] = 999.0
    dataset["water_temp"].values[1, 1:, 1:, 1:] = selected

    product = _product(dataset, maximum_points=3)

    assert product.full_subset_range.minimum == -999.0
    assert product.full_subset_range.maximum == 999.0
    assert product.delivered_sample_range.minimum != -999.0
    assert product.delivered_sample_range.maximum != 999.0


def test_units_dimensions_identity_provenance_and_schema_are_preserved():
    product = _product(maximum_points=5)

    assert product.schema_version == PRODUCT_SCHEMA_VERSION
    assert product.variable_units == "degree_Celsius"
    assert product.source_dtype == "float32"
    assert product.identity.dataset_id == "hycom-glby008"
    assert product.identity.dataset_version_id == "import-123"
    assert product.dimensions.source_order == ("time", "depth", "lat", "lon")
    assert product.dimensions.semantic_order == ("depth", "lat", "lon")
    assert product.coordinates.units["depth"] == "m"
    assert product.coordinates.units["latitude"] == "degrees_north"
    assert product.provenance["import_id"] == "import-123"
    assert product.provenance["steps"] == ("decoded", "validated")
    assert product.sampling.policy == SAMPLING_POLICY
    assert "traversal" in product.sampling.parameters


@pytest.mark.parametrize("variable", ["not_present", "lat"])
def test_invalid_or_missing_variable_has_an_actionable_error(variable: str):
    with pytest.raises(VariableSelectionError, match="available data variables"):
        _product(variable=variable)


def test_unavailable_time_is_rejected():
    selection = replace(_selection(), time=np.datetime64("2030-01-01"))

    with pytest.raises(TimeSelectionError, match="unavailable"):
        subset_scalar_field(_dataset(), _descriptor(), selection)


def test_duplicate_matching_times_are_rejected_as_ambiguous():
    dataset = _dataset().assign_coords(
        time=np.array(["2026-01-02", "2026-01-02"],
                      dtype="datetime64[ns]"))

    with pytest.raises(TimeSelectionError, match="matches 2 source cells"):
        subset_scalar_field(dataset, _descriptor(), _selection())


def test_curvilinear_grid_is_rejected_instead_of_guessed():
    dataset = _dataset().rename({"lat": "y", "lon": "x"})
    dataset = dataset.assign_coords(
        lat=(("y", "x"), np.broadcast_to([-10.0, 0.0, 10.0], (4, 3)).T),
        lon=(("y", "x"), np.broadcast_to([60.0, 70.0, 80.0, 90.0],
                                          (3, 4))),
    )

    with pytest.raises(GridValidationError, match="one-dimensional"):
        subset_scalar_field(dataset, _descriptor(), _selection())


def test_variable_with_an_extra_grid_dimension_is_rejected():
    dataset = _dataset()
    dataset["water_temp"] = dataset["water_temp"].expand_dims(member=[0])

    with pytest.raises(GridValidationError, match="exactly the time"):
        subset_scalar_field(dataset, _descriptor(), _selection())


def test_bounds_that_select_no_cells_are_actionable():
    selection = replace(
        _selection(),
        area=GeographicBounds(west=100.0, east=110.0,
                              south=-1.0, north=10.0),
    )

    with pytest.raises(EmptySubsetError, match="available extent"):
        subset_scalar_field(_dataset(), _descriptor(), selection)


def test_invalid_bounds_and_point_budgets_are_typed_errors():
    with pytest.raises(InvalidRequestError, match="antimeridian"):
        GeographicBounds(west=170.0, east=-170.0,
                         south=-10.0, north=10.0)
    with pytest.raises(PointBudgetError, match="positive integer"):
        SamplingRequest(maximum_points=0)
    with pytest.raises(PointBudgetError, match="unsupported sampling"):
        SamplingRequest(maximum_points=5, policy="random")


def test_processing_does_not_mutate_the_input_dataset():
    dataset = _dataset()
    original = dataset.copy(deep=True)

    _product(dataset, maximum_points=5)

    xr.testing.assert_identical(dataset, original)


def test_every_coordinate_and_value_comes_from_the_selected_source_cell():
    dataset = _dataset()
    product = _product(dataset, maximum_points=7)

    for point, source in enumerate(product.points.source_indices):
        assert product.points.longitude[point] == dataset.lon.values[source.longitude]
        assert product.points.latitude[point] == dataset.lat.values[source.latitude]
        assert product.points.depth[point] == dataset.depth.values[source.depth]
        source_value = dataset.water_temp.values[
            source.time, source.depth, source.latitude, source.longitude]
        assert product.points.values[point] == source_value


def test_product_arrays_are_read_only_snapshots():
    product = _product()

    with pytest.raises(ValueError, match="read-only"):
        product.points.values[0] = 100.0


def test_envelope_declares_reference_transform_mask_and_time_encoding():
    dataset = _dataset()
    dataset["time"].encoding.update(
        {"units": "hours since 2000-01-01 00:00:00", "calendar": "gregorian"})

    product = _product(dataset)

    assert product.spatial_reference == SpatialReference(
        crs="EPSG:4326", vertical_positive="down")
    assert product.coordinate_transform == IDENTITY_TRANSFORM
    assert product.mask_semantics == MISSING_VALUE_MASK
    assert product.coordinates.time_encoding["units"] == \
        "hours since 2000-01-01 00:00:00"
    assert product.coordinates.time_encoding["calendar"] == "gregorian"
    assert product.coordinates.dtypes["time"] == "datetime64[ns]"
    assert product.coordinates.dtypes["depth"] == "float64"


def test_undeclared_time_encoding_is_recorded_as_absent_not_defaulted():
    product = _product()

    assert product.coordinates.time_encoding["calendar"] is None
    assert product.coordinates.time_encoding["units"] is None


def test_source_vertical_direction_must_agree_with_the_declared_one():
    dataset = _dataset()
    dataset["depth"].attrs["positive"] = "down"
    assert _product(dataset).spatial_reference.vertical_positive == "down"

    with pytest.raises(GridValidationError, match="contradicting"):
        subset_scalar_field(dataset, _descriptor(vertical_positive="up"),
                            _selection())


def test_spatial_reference_must_be_declared_explicitly():
    with pytest.raises(InvalidRequestError, match="coordinate reference"):
        SpatialReference(crs="", vertical_positive="down")
    with pytest.raises(InvalidRequestError, match="vertical_positive"):
        SpatialReference(crs="EPSG:4326", vertical_positive="depth")


def test_sampling_declares_its_basis_and_counts_cells_and_valid_values_apart():
    dataset = _dataset()
    values = dataset["water_temp"].values.copy()
    values[1, 1, 1, 1] = np.nan   # subset flat index 0, which is sampled
    values[1, 1, 1, 2] = np.nan   # subset flat index 1, which is not
    dataset["water_temp"].values = values

    product = _product(dataset, maximum_points=5)

    assert product.sampling.parameters["basis"].startswith("index space")
    assert product.sampling.parameters["masked_cells_eligible"] is True
    assert product.sampling.original_point_count == 12
    assert product.sampling.original_valid_point_count == 10
    assert product.sampling.delivered_point_count == 5
    assert product.sampling.delivered_valid_point_count == 4


def test_an_all_missing_subset_is_a_typed_failure_not_an_empty_product():
    dataset = _dataset()
    dataset["water_temp"].values = np.full(
        dataset["water_temp"].shape, np.nan, dtype=np.float32)

    with pytest.raises(AllMissingSubsetError, match="all 12 selected cells"):
        _product(dataset)


def test_dataset_version_is_explicit_and_provenance_cannot_contradict_it():
    with pytest.raises(InvalidRequestError, match="dataset_version_id"):
        DatasetIdentity(dataset_id="hycom-glby008", dataset_version_id=" ")
    with pytest.raises(InvalidRequestError, match="contradicts"):
        _descriptor(provenance={"import_id": "import-999"})


def test_provenance_is_a_json_compatible_deep_copy():
    source = {"steps": ["decoded"], "detail": {"levels": np.int64(40)}}
    descriptor = _descriptor(provenance=source)
    source["steps"].append("tampered")
    source["detail"]["levels"] = 0

    assert descriptor.provenance["steps"] == ("decoded",)
    assert descriptor.provenance["detail"]["levels"] == 40
    assert type(descriptor.provenance["detail"]["levels"]) is int


@pytest.mark.parametrize("leaf", [{"a", "b"}, bytearray(b"x"), object(),
                                  float("nan")])
def test_provenance_refuses_values_that_are_mutable_or_not_json(leaf):
    with pytest.raises(InvalidRequestError, match="metadata.bad"):
        _descriptor(provenance={"bad": leaf})
