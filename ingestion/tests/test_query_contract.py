"""Shared contract tests for replaceable S3 model-field queries."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import psycopg
import pytest

from ingestion.config import SOURCE_REFERENCES
from ingestion.canonical import collect_metadata
from ingestion.query import (
    ManagedFieldClosed, ManagedModelField, ModelFieldQueryError,
    NotAModelField, ObservationProfile, ProfileIdentity, ProfileMarker,
    ProfileNotFound, ProfileSearch, ProfileVariable,
    UndeclaredReference, VariableUnavailable, VersionNotFound,
)
from ingestion.storage.objects import LocalObjectStore
from ingestion.storage.postgres import PostgresStorage
from ingestion.storage.query import CatalogueModelFieldQuery
from ingestion.tests.query_support import (
    QueryContractCase, in_memory_case, live_dsn_status, model_package,
    profile_package, rebuild_live_catalogue,
)


@pytest.fixture(scope="module")
def catalogue_case(tmp_path_factory) -> QueryContractCase:
    dsn, reason = live_dsn_status()
    if reason is not None:
        pytest.skip(reason)
    assert dsn is not None
    rebuild_live_catalogue(dsn)
    objects = LocalObjectStore(tmp_path_factory.mktemp("contract-objects"))
    model = model_package()
    profile = profile_package()
    storage = PostgresStorage(dsn, objects)
    storage.hand_off(model)
    storage.hand_off(profile)
    return QueryContractCase(
        query=CatalogueModelFieldQuery(
            dsn, objects, SOURCE_REFERENCES),
        model_version_id=model.import_id,
        profile_version_id=profile.import_id,
        undeclared_query=CatalogueModelFieldQuery(dsn, objects, {}),
        undeclared_version_id=model.import_id,
    )


@pytest.fixture(params=(
    "memory",
    pytest.param("catalogue", marks=pytest.mark.live),
))
def query_case(request) -> QueryContractCase:
    if request.param == "memory":
        return in_memory_case()
    return request.getfixturevalue("catalogue_case")


def test_contract_lists_describes_and_opens_a_model_field(query_case):
    versions = query_case.query.list_model_versions()
    summary = query_case.query.describe_version(
        query_case.model_version_id)

    assert summary in versions
    assert summary.id == query_case.model_version_id
    assert summary.dataset == "GLBy0.08_expt_93.0"
    assert summary.geometry == "grid"
    assert [(item.name, item.units) for item in summary.variables] == [
        ("salinity", "1e-3"),
        ("water_temp", "degree_Celsius"),
    ]
    assert summary.depth_levels == 3
    assert summary.time_steps == 1
    assert summary.depth_values == (0.0, 10.0, 20.0)
    assert len(summary.time_values) == 1
    assert summary.time_values[0].startswith("2026-09-28T00:00:00")
    assert summary.extent.depth_min == 0.0
    assert summary.extent.depth_max == 20.0
    assert summary.extent.vertical_min == 0.0
    assert summary.extent.vertical_max == 20.0
    assert summary.extent.vertical_kind == "depth"
    assert summary.extent.vertical_units == "m"
    assert summary.extent.east == 75.0
    assert all(item.geometry == "grid" for item in versions)
    assert versions.unavailable == ()

    managed = query_case.query.open_model_field(
        query_case.model_version_id, "water_temp")
    with managed as opened:
        assert set(opened.dataset.data_vars) == {"water_temp"}
        data = opened.dataset["water_temp"]
        assert tuple(data.dims) == ("time", "depth", "lat", "lon")
        assert data.attrs["units"] == "degree_Celsius"
        assert np.isnan(data.values[0, 1, 1, 2])
        descriptor = opened.descriptor
        assert descriptor.dataset_id == "GLBy0.08_expt_93.0"
        assert descriptor.dataset_version_id == query_case.model_version_id
        assert descriptor.source_id == "hycom_opendap"
        assert descriptor.variable == "water_temp"
        assert descriptor.standard_name == "sea_water_temperature"
        assert descriptor.time_coordinate == "time"
        assert descriptor.depth_coordinate == "depth"
        assert descriptor.latitude_coordinate == "lat"
        assert descriptor.longitude_coordinate == "lon"
        assert descriptor.crs == "EPSG:4326"
        assert descriptor.vertical_positive == "down"
        assert descriptor.provenance["import_id"] == (
            query_case.model_version_id)
    assert managed.closed
    with pytest.raises(ManagedFieldClosed):
        _ = managed.dataset


def test_contract_selects_variables_generically(query_case):
    with query_case.query.open_model_field(
            query_case.model_version_id, "salinity") as managed:
        assert set(managed.dataset.data_vars) == {"salinity"}
        assert managed.descriptor.variable == "salinity"
        assert managed.descriptor.units == "1e-3"


def test_contract_reports_a_missing_version(query_case):
    with pytest.raises(VersionNotFound):
        query_case.query.describe_version("does-not-exist")


def test_contract_refuses_non_model_geometry(query_case):
    with pytest.raises(NotAModelField):
        query_case.query.open_model_field(
            query_case.profile_version_id, "TEMP")


def test_contract_reports_an_unavailable_variable(query_case):
    with pytest.raises(VariableUnavailable):
        query_case.query.open_model_field(
            query_case.model_version_id, "chlorophyll")


def test_contract_refuses_an_undeclared_scientific_reference(query_case):
    with pytest.raises(UndeclaredReference):
        query_case.undeclared_query.open_model_field(
            query_case.undeclared_version_id, "water_temp")


def test_contract_finds_markers_and_retrieves_an_exact_profile(query_case):
    markers = query_case.query.find_profile_markers(ProfileSearch(
        west=73.0, east=74.0, south=8.0, north=9.0,
        time_start="2026-09-27T00:00:00Z",
        time_end="2026-09-29T00:00:00Z",
    ))

    assert len(markers) == 1
    marker = markers[0]
    assert marker.identity == ProfileIdentity(
        query_case.profile_version_id, "7902250", "12")
    assert marker.longitude == pytest.approx(73.5)
    assert marker.latitude == pytest.approx(8.5)
    assert marker.observed_at.startswith("2026-09-28")
    assert marker.representative_source_index == 0

    profile = query_case.query.get_profile(marker.identity)
    assert profile.identity == marker.identity
    assert profile.depth_coordinate == "PRES"
    assert profile.depth_units == "decibar"
    assert profile.depth_values == (2.0, 10.0)
    assert profile.time_coordinate == "time"
    assert len(profile.timestamps) == 2
    assert all(value is not None and value.startswith("2026-09-28")
               for value in profile.timestamps)
    assert profile.source_indices == (0, 1)
    assert profile.depth_source_dtype == "float64"
    assert profile.time_source_dtype == "datetime64[ns]"
    assert profile.time_encoding == {
        "units": "days since 1970-01-01",
        "calendar": "proleptic_gregorian",
    }
    variables = {variable.name: variable for variable in profile.variables}
    assert set(variables) == {"PSAL", "TEMP"}
    assert variables["TEMP"].units == "degree_Celsius"
    assert variables["TEMP"].values == (28.0, 27.5)
    assert variables["TEMP"].source_dtype == "float64"
    assert variables["TEMP"].quality_control_name == "TEMP_QC"
    assert variables["TEMP"].quality_control == ("1", "2")
    assert variables["TEMP"].qc_source_dtype is not None
    assert variables["TEMP"].qc_flag_values == (1, 2)
    assert variables["TEMP"].qc_flag_meanings == "good_data bad_data"
    assert variables["TEMP"].qc_conventions == "fixture QC table 1"
    assert variables["PSAL"].units == "1e-3"
    assert variables["PSAL"].values == (34.8, 35.1)
    assert variables["PSAL"].quality_control == ("1", "1")
    assert variables["PSAL"].qc_flag_values is None
    assert variables["PSAL"].qc_flag_meanings is None
    assert variables["PSAL"].qc_conventions is None


def test_contract_profile_lookup_respects_bounds_and_reports_missing_identity(
        query_case):
    outside = query_case.query.find_profile_markers(ProfileSearch(
        west=74.0, east=75.0, south=8.0, north=9.0,
        time_start="2026-09-27T00:00:00Z",
        time_end="2026-09-29T00:00:00Z",
    ))
    assert outside == ()

    with pytest.raises(ProfileNotFound):
        query_case.query.get_profile(ProfileIdentity(
            query_case.profile_version_id, "7902250", "missing-cycle"))


@pytest.mark.live
def test_live_catalogue_listing_uses_persisted_coordinates_without_object_read(
        catalogue_case):
    dsn, reason = live_dsn_status()
    assert reason is None
    assert dsn is not None
    with psycopg.connect(dsn) as connection:
        stored = connection.execute(
            "SELECT time_values, depth_values FROM dataset_version "
            "WHERE import_id = %s",
            (catalogue_case.model_version_id,),
        ).fetchone()
    assert stored == (
        ["2026-09-28T00:00:00.000000000"],
        [0.0, 10.0, 20.0],
    )

    class ObjectReadsForbidden:
        def open(self, reference):
            raise AssertionError(f"unexpected object read: {reference}")

    query = CatalogueModelFieldQuery(
        dsn, ObjectReadsForbidden(), SOURCE_REFERENCES)
    listing = query.list_model_versions()

    assert [item.id for item in listing] == [
        catalogue_case.model_version_id]
    assert listing.unavailable == ()


@pytest.mark.live
def test_schema_migrates_legacy_vertical_extents_idempotently(catalogue_case):
    dsn, reason = live_dsn_status()
    assert reason is None
    assert dsn is not None
    schema = (Path(__file__).parents[1] / "storage" / "migrations"
              / "0001_catalogue_baseline.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "UPDATE dataset_version SET vertical_min = NULL, "
            "vertical_max = NULL, vertical_kind = NULL, "
            "vertical_units = NULL, depth_min = 2.0, depth_max = 10.0 "
            "WHERE import_id = %s",
            (catalogue_case.profile_version_id,),
        )
        connection.execute(
            "UPDATE observation_profile SET vertical_min = NULL, "
            "vertical_max = NULL, vertical_kind = NULL, "
            "vertical_units = NULL, depth_min = 2.0, depth_max = 10.0 "
            "WHERE import_id = %s",
            (catalogue_case.profile_version_id,),
        )
        connection.execute(schema)
        connection.execute(schema)
        version_extent = connection.execute(
            "SELECT vertical_min, vertical_max, vertical_kind, "
            "vertical_units, depth_min, depth_max FROM dataset_version "
            "WHERE import_id = %s",
            (catalogue_case.profile_version_id,),
        ).fetchone()
        profile_extent = connection.execute(
            "SELECT vertical_min, vertical_max, vertical_kind, "
            "vertical_units, depth_min, depth_max FROM observation_profile "
            "WHERE import_id = %s",
            (catalogue_case.profile_version_id,),
        ).fetchone()

    expected = (2.0, 10.0, "pressure", "decibar", None, None)
    assert version_extent == expected
    assert profile_extent == expected


@pytest.mark.live
def test_live_catalogue_persists_one_antimeridian_source_row(
        catalogue_case, tmp_path):
    dsn, reason = live_dsn_status()
    assert reason is None
    assert dsn is not None
    base = profile_package(import_id="antimeridian-profile")
    dataset = base.dataset.assign_coords(
        time=(
            "observation",
            np.array(["2026-09-28", "2026-09-27"], dtype="datetime64[ns]"),
        ),
        latitude=("observation", [8.0, 10.0]),
        longitude=("observation", [179.0, -179.0]),
    )
    dataset["time"].encoding.update(base.dataset["time"].encoding)
    package = replace(
        base,
        dataset=dataset,
        metadata=collect_metadata(dataset, base.coordinates),
    )
    objects = LocalObjectStore(tmp_path / "antimeridian-objects")
    PostgresStorage(dsn, objects).hand_off(package)

    try:
        query = CatalogueModelFieldQuery(dsn, objects, SOURCE_REFERENCES)
        markers = query.find_profile_markers(ProfileSearch(
            west=178.0,
            east=180.0,
            south=7.0,
            north=9.0,
            time_start="2026-09-27T00:00:00Z",
            time_end="2026-09-29T00:00:00Z",
        ))

        assert len(markers) == 1
        assert markers[0].longitude == 179.0
        assert markers[0].latitude == 8.0
        assert markers[0].observed_at.startswith("2026-09-28")
        assert markers[0].representative_source_index == 0
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                "DELETE FROM dataset_version WHERE import_id = %s",
                (package.import_id,),
            )


def test_legacy_profile_contract_metadata_is_explicitly_absent():
    identity = ProfileIdentity("legacy", "float", "1")
    marker = ProfileMarker(identity, 73.0, 8.0, "2026-09-28T00:00:00Z")
    variable = ProfileVariable("TEMP", "degree_Celsius", (28.0,))
    profile = ObservationProfile(
        identity=identity,
        depth_coordinate="PRES",
        depth_units="decibar",
        depth_values=(2.0,),
        time_coordinate="time",
        timestamps=("2026-09-28T00:00:00Z",),
        variables=(variable,),
    )

    assert marker.representative_source_index is None
    assert variable.source_dtype is None
    assert variable.qc_source_dtype is None
    assert profile.source_indices is None
    assert profile.depth_source_dtype is None
    assert profile.time_source_dtype is None
    assert profile.time_encoding is None


def test_contract_and_managed_handoff_import_without_storage_or_psycopg():
    code = """
import sys
import ingestion.query
import processing.managed
assert 'psycopg' not in sys.modules
assert not any(name == 'ingestion.storage' or name.startswith('ingestion.storage.')
               for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_managed_close_failures_do_not_leak_backend_details():
    case = in_memory_case()
    with case.query.open_model_field(
            case.model_version_id, "water_temp") as opened:
        managed = ManagedModelField(
            opened.dataset,
            opened.descriptor,
            close=lambda: (_ for _ in ()).throw(
                RuntimeError("/private/object.nc")),
        )
    with pytest.raises(ModelFieldQueryError) as failure:
        managed.close()
    assert "/private/object.nc" not in str(failure.value)
    assert managed.closed


def test_contract_describes_observation_versions_from_the_catalogue(query_case):
    listing = query_case.query.list_observation_versions()
    described = query_case.query.describe_observation_version(
        query_case.profile_version_id)

    assert [v.dataset_version_id for v in listing] == [
        query_case.profile_version_id]
    assert described == listing[0]
    assert described.vertical_coordinate == "PRES"
    assert described.vertical_units == "decibar"
    assert described.vertical_kind == "pressure"
    assert described.extent.vertical_min == 2.0
    assert described.extent.vertical_max == 10.0
    assert described.extent.vertical_kind == "pressure"
    assert described.extent.vertical_units == "decibar"
    assert described.extent.depth_min is None
    assert described.extent.depth_max is None
    assert described.crs == "EPSG:4326"
    assert described.vertical_positive == "down"
    assert {v.name for v in described.variables} == {"PSAL", "TEMP"}


def test_contract_refuses_to_describe_a_model_grid_as_observations(query_case):
    with pytest.raises(ModelFieldQueryError):
        query_case.query.describe_observation_version(
            query_case.model_version_id)


def test_catalogue_reports_observations_without_declared_references(
        catalogue_case):
    undeclared = catalogue_case.undeclared_query
    listing = undeclared.list_observation_versions()

    assert catalogue_case.profile_version_id in [
        item.id for item in listing.unavailable]
    with pytest.raises(UndeclaredReference):
        undeclared.describe_observation_version(
            catalogue_case.profile_version_id)


def test_memory_reports_observations_without_declared_semantics():
    from dataclasses import replace

    from ingestion.query_memory import InMemoryModelFieldQuery

    case = in_memory_case()
    bare = [replace(v, observation=None) for v in case.query._versions.values()]
    query = InMemoryModelFieldQuery(bare)

    assert case.profile_version_id in [
        item.id for item in query.list_observation_versions().unavailable]
    with pytest.raises(UndeclaredReference):
        query.describe_observation_version(case.profile_version_id)


def test_vertical_kind_comes_from_units_and_refuses_the_unknown():
    from ingestion.query import observation_vertical_kind

    assert observation_vertical_kind("decibar") == "pressure"
    assert observation_vertical_kind(" dbar ") == "pressure"
    assert observation_vertical_kind("m") == "depth"
    assert observation_vertical_kind("fathoms") is None
    assert observation_vertical_kind(None) is None
