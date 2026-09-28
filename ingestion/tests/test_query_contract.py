"""Shared contract tests for replaceable S3 model-field queries."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from ingestion.config import MODEL_SOURCE_REFERENCES
from ingestion.query import (
    ManagedFieldClosed, ManagedModelField, ModelFieldQueryError,
    NotAModelField, ProfileIdentity, ProfileNotFound, ProfileSearch,
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
            dsn, objects, MODEL_SOURCE_REFERENCES),
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

    profile = query_case.query.get_profile(marker.identity)
    assert profile.identity == marker.identity
    assert profile.depth_coordinate == "PRES"
    assert profile.depth_units == "m"
    assert profile.depth_values == (2.0, 10.0)
    assert profile.time_coordinate == "time"
    assert len(profile.timestamps) == 2
    assert all(value is not None and value.startswith("2026-09-28")
               for value in profile.timestamps)
    variables = {variable.name: variable for variable in profile.variables}
    assert set(variables) == {"PSAL", "TEMP"}
    assert variables["TEMP"].units == "degree_Celsius"
    assert variables["TEMP"].values == (28.0, 27.5)
    assert variables["TEMP"].quality_control_name == "TEMP_QC"
    assert variables["TEMP"].quality_control == ("1", "2")
    assert variables["PSAL"].units == "1e-3"
    assert variables["PSAL"].values == (34.8, 35.1)
    assert variables["PSAL"].quality_control == ("1", "1")


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
