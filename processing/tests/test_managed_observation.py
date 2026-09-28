"""S3 observation records bind directly to S4 product builders."""

from __future__ import annotations

import pytest

from ingestion.query import ProfileIdentity, ProfileSearch
from ingestion.tests.query_support import PROFILE_VERSION_ID, in_memory_case
from processing import (
    DatasetIdentity, InvalidRequestError, ManagedDataUnavailableError,
    WorkLimitError,
    ObservationRecordDescriptor, SpatialReference,
)
from processing.managed import (
    ManagedObservationMarkerRequest, ManagedObservationProfileRequest,
    managed_observation_marker_builder,
    managed_observation_profile_builder,
)


def _descriptor() -> ObservationRecordDescriptor:
    return ObservationRecordDescriptor(
        identity=DatasetIdentity("Indian_ARGO_Floats", PROFILE_VERSION_ID),
        spatial_reference=SpatialReference(
            crs="EPSG:4326", vertical_positive="down"),
        vertical_kind="depth",
        provenance={
            "import_id": PROFILE_VERSION_ID,
            "source": {"id": "incois_erddap"},
        },
    )


def _search() -> ProfileSearch:
    return ProfileSearch(
        west=73.0, east=74.0, south=8.0, north=9.0,
        time_start="2026-09-27T00:00:00Z",
        time_end="2026-09-29T00:00:00Z",
    )


def test_managed_marker_builder_consumes_only_s3_records(monkeypatch):
    query = in_memory_case().query

    def refuse_open(*args, **kwargs):
        raise AssertionError("observation products must not reopen xarray data")

    monkeypatch.setattr(query, "open_model_field", refuse_open)
    builder = managed_observation_marker_builder(
        query, {PROFILE_VERSION_ID: _descriptor()})

    product = builder(ManagedObservationMarkerRequest(
        dataset_version_id=PROFILE_VERSION_ID, search=_search()))

    assert product.dataset_identity.dataset_version_id == PROFILE_VERSION_ID
    assert len(product.markers) == 1
    marker = product.markers[0]
    assert marker.identity.platform_id == "7902250"
    assert marker.identity.cycle == "12"
    assert marker.longitude == pytest.approx(73.5)
    assert marker.vertical_range.minimum == 2.0
    assert marker.vertical_range.maximum == 10.0
    assert marker.source_indices == (0, 1)
    assert product.coordinate_transform.kind == "s3-observation-record"
    assert "ProfileMarker" in product.grouping.representative_policy


def test_managed_profile_builder_preserves_exact_record_values_and_qc():
    case = in_memory_case()
    builder = managed_observation_profile_builder(
        case.query, {PROFILE_VERSION_ID: _descriptor()})

    product = builder(ManagedObservationProfileRequest(
        identity=ProfileIdentity(PROFILE_VERSION_ID, "7902250", "12"),
        variables=("TEMP", "PSAL"),
    ))

    assert product.source_indices == (0, 1)
    assert product.vertical_values.tolist() == [2.0, 10.0]
    assert product.coordinates.names.vertical == "PRES"
    assert product.coordinates.names.time == "time"
    assert product.coordinates.units["vertical"] == "decibar"
    temperature, salinity = product.variables
    assert temperature.values.tolist() == [28.0, 27.5]
    assert temperature.source_dtype is None
    assert temperature.qc_flags.tolist() == ["1", "2"]
    assert temperature.qc_source_dtype is None
    assert temperature.qc_flag_values == (1, 2)
    assert temperature.qc_flag_meanings == "good_data bad_data"
    assert temperature.qc_conventions == "fixture QC table 1"
    assert salinity.values.tolist() == [34.8, 35.1]
    assert product.provenance["import_id"] == PROFILE_VERSION_ID


def test_managed_profile_builder_reports_s3_lookup_failure():
    case = in_memory_case()
    builder = managed_observation_profile_builder(
        case.query, {PROFILE_VERSION_ID: _descriptor()})

    with pytest.raises(ManagedDataUnavailableError, match="does not exist"):
        builder(ManagedObservationProfileRequest(
            identity=ProfileIdentity(
                PROFILE_VERSION_ID, "7902250", "missing"),
            variables=("TEMP",),
        ))


def test_managed_observation_descriptor_must_match_requested_version():
    case = in_memory_case()
    wrong = ObservationRecordDescriptor(
        identity=DatasetIdentity("Indian_ARGO_Floats", "wrong-version"),
        spatial_reference=SpatialReference(
            crs="EPSG:4326", vertical_positive="down"),
        vertical_kind="depth",
        provenance={"import_id": "wrong-version"},
    )
    builder = managed_observation_marker_builder(
        case.query, {PROFILE_VERSION_ID: wrong})

    with pytest.raises(InvalidRequestError, match="contradicts requested"):
        builder(ManagedObservationMarkerRequest(
            dataset_version_id=PROFILE_VERSION_ID, search=_search()))


def test_observation_semantics_are_resolved_from_s3_per_request():
    case = in_memory_case()
    build = managed_observation_profile_builder(case.query)

    product = build(ManagedObservationProfileRequest(
        identity=ProfileIdentity(PROFILE_VERSION_ID, "7902250", "12"),
        variables=("TEMP",)))

    assert product.coordinates.vertical_kind == "pressure"
    assert product.spatial_reference.crs == "EPSG:4326"


def test_an_undescribed_observation_version_is_a_data_failure():
    from dataclasses import replace

    from ingestion.query_memory import InMemoryModelFieldQuery

    case = in_memory_case()
    bare = InMemoryModelFieldQuery(
        [replace(v, observation=None) for v in case.query._versions.values()])
    build = managed_observation_marker_builder(bare)

    with pytest.raises(ManagedDataUnavailableError, match="observation semantics"):
        build(ManagedObservationMarkerRequest(PROFILE_VERSION_ID, _search()))


def test_the_marker_ceiling_is_checked_before_any_profile_is_read(monkeypatch):
    case = in_memory_case()

    def forbidden(identity):
        raise AssertionError("a profile was read past the marker ceiling")

    monkeypatch.setattr(case.query, "get_profile", forbidden)
    build = managed_observation_marker_builder(case.query, maximum_markers=0)

    with pytest.raises(WorkLimitError, match="at most 0 markers"):
        build(ManagedObservationMarkerRequest(PROFILE_VERSION_ID, _search()))
