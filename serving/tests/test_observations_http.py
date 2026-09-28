"""Observation markers and exact profiles over HTTP, on the S3 fake."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ingestion.query_memory import InMemoryModelFieldQuery
from ingestion.tests.query_support import PROFILE_VERSION_ID, in_memory_case
from processing import LocalExecutor
from processing.managed import (
    managed_observation_marker_builder, managed_observation_profile_builder,
)
from processing.tests import fixtures
from serving import wire_observation
from serving.coordinator import RequestCoordinator
from serving.http import create_app
from serving.observations import ObservationService

MARKERS = "/api/v1/observation-markers"
PROFILES = "/api/v1/observation-profiles"
SEARCH = {"dataset_version_id": PROFILE_VERSION_ID, "west": 70, "east": 80,
          "south": 5, "north": 12, "time_start": "2026-09-27T00:00:00Z",
          "time_end": "2026-09-29T00:00:00Z"}
PROFILE = {"dataset_version_id": PROFILE_VERSION_ID, "platform_id": "7902250",
           "cycle": "12", "variables": ["TEMP", "PSAL"]}


def _client(query=None, maximum_markers=None) -> TestClient:
    query = query or in_memory_case().query
    service = ObservationService(
        markers=managed_observation_marker_builder(
            query, maximum_markers=maximum_markers),
        profiles=managed_observation_profile_builder(query))
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    return TestClient(create_app(RequestCoordinator(executor), query,
                                 observations=service))


def test_markers_are_described_then_fetched_as_binary_from_the_same_query():
    client = _client()
    described = client.get(MARKERS, params=SEARCH).json()

    assert described["wire_format"] == wire_observation.WIRE_FORMAT
    data = client.get(described["data"]["url"])
    assert data.status_code == 200
    assert data.headers["content-type"] == wire_observation.MEDIA_TYPE
    assert len(data.content) == described["data"]["byte_length"]
    arrays = wire_observation.decode_arrays(described["data"]["arrays"], data.content)
    assert arrays  # every declared array is readable from the buffer


def test_the_same_query_always_yields_the_same_bytes():
    client = _client()
    url = client.get(MARKERS, params=SEARCH).json()["data"]["url"]

    assert client.get(url).content == client.get(url).content


def test_an_exact_profile_carries_its_pressure_axis_and_qc():
    client = _client()
    described = client.get(PROFILES, params=PROFILE).json()
    product = described["product"]

    assert product["coordinates"]["vertical_kind"] == "pressure"
    assert product["coordinates"]["units"]["vertical"] == "decibar"
    data = client.get(described["data"]["url"])
    assert len(data.content) == described["data"]["byte_length"]


@pytest.mark.parametrize("change, status, code", [
    ({"time_start": "tomorrow"}, 400, "invalid_request"),
    ({"west": 90, "east": 80}, 400, "invalid_request"),
    ({"dataset_version_id": "no-such-version"}, 404, "data_unavailable"),
])
def test_marker_failures_carry_codes(change, status, code):
    response = _client().get(MARKERS, params={**SEARCH, **change})

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_an_unknown_profile_is_not_found_and_a_wide_search_is_refused():
    unknown = _client().get(PROFILES, params={**PROFILE, "cycle": "999"})
    assert unknown.status_code == 404

    capped = _client(maximum_markers=0).get(MARKERS, params=SEARCH)
    assert capped.status_code == 422
    assert capped.json()["detail"]["code"] == "work_limit"


def test_the_catalogue_lists_observation_versions_and_undescribed_ones():
    case = in_memory_case()
    body = _client(case.query).get("/api/v1/catalogue").json()
    assert [v["dataset_version_id"] for v in body["observation_versions"]] == [
        PROFILE_VERSION_ID]
    assert body["observation_versions"][0]["vertical_kind"] == "pressure"

    bare = InMemoryModelFieldQuery(
        [replace(v, observation=None) for v in case.query._versions.values()])
    body = _client(bare).get("/api/v1/catalogue").json()
    assert body["observation_versions"] == []
    assert [u["id"] for u in body["observation_unavailable"]] == [PROFILE_VERSION_ID]


def test_without_an_observation_service_the_routes_say_so():
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    client = TestClient(create_app(RequestCoordinator(executor)))

    response = client.get(MARKERS, params=SEARCH)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "observations_unavailable"
