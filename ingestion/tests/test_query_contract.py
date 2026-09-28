"""Shared contract tests for replaceable S3 model-field queries."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from ingestion.config import MODEL_SOURCE_REFERENCES
from ingestion.query import (
    ManagedFieldClosed, ManagedModelField, ModelFieldQueryError,
    NotAModelField, UndeclaredReference,
    VariableUnavailable, VersionNotFound,
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
    assert summary.extent.depth_min == 0.0
    assert summary.extent.east == 75.0
    assert all(item.geometry == "grid" for item in versions)

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
