"""The HTTP surface translates; the coordinator and executor decide."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ingestion.query import (
    DatasetVersionListing, ObservationVersionListing, UnavailableDatasetVersion,
)
from processing import (
    ExecutorCapabilities, JobState, LocalExecutor, ProductExecutor,
    ProductJob, UnknownRequestError,
)
from processing.tests import fixtures
from serving import compose, wire
from serving.coordinator import RequestCoordinator
from serving.http import create_app

BODY = {
    "dataset_version_id": fixtures.VERSION, "variable": "water_temp",
    "time": "2026-01-02T00:00:00Z", "west": 65.0, "east": 90.0,
    "south": -1.0, "north": 10.0, "depth_minimum": 5.0,
    "depth_maximum": 20.0, "maximum_points": 5,
}


@pytest.fixture()
def client() -> TestClient:
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    return TestClient(create_app(RequestCoordinator(executor)))


def test_health_and_capabilities(client):
    assert client.get("/health").json() == {"status": "ok", "stage": "S5"}
    capabilities = client.get("/api/v1/capabilities").json()
    assert capabilities["wire_format"] == wire.WIRE_FORMAT
    assert capabilities["executor"]["maximum_points"] == 100
    assert capabilities["executor"]["cancellation"] is False


def test_a_product_is_requested_described_and_fetched_as_binary(client):
    accepted = client.post("/api/v1/point-fields", json=BODY)
    assert accepted.status_code == 202
    view = accepted.json()
    assert accepted.headers["location"] == view["links"]["self"]
    assert view["state"] == "succeeded" and view["finished"] is True

    status = client.get(view["links"]["self"]).json()
    described = status["product"]
    assert described["point_count"] == 5

    data = client.get(described["data"]["url"])
    assert data.status_code == 200
    assert data.headers["content-type"] == wire.MEDIA_TYPE
    assert len(data.content) == described["data"]["byte_length"]
    arrays = wire.decode(described["data"]["arrays"], data.content)
    expected = LocalExecutor(fixtures.builder(), maximum_points=100, maximum_cells=1000).submit(
        fixtures.request(5)).product
    np.testing.assert_array_equal(arrays["values"], expected.points.values)


@pytest.mark.parametrize("field, value, code", [
    ("time", "yesterday", "invalid_request"),
    ("time", "NaT", "invalid_request"),
    ("west", 170.0, "invalid_request"),
    ("maximum_points", 0, "point_budget"),
])
def test_invalid_requests_are_rejected_with_a_code(client, field, value, code):
    response = client.post("/api/v1/point-fields", json={**BODY, field: value})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == code


def test_a_budget_over_the_server_ceiling_is_reduced_and_disclosed(client):
    over = client.post("/api/v1/point-fields",
                       json={**BODY, "maximum_points": 1000}).json()
    under = client.post("/api/v1/point-fields", json=BODY).json()

    assert over["state"] == "succeeded"
    assert over["budget"] == {"requested_points": 1000,
                              "effective_points": 100,
                              "reduced_by_server": True,
                              "maximum_cells": 1000}
    assert over["product"]["product"]["sampling"]["maximum_points"] == 100
    assert under["budget"]["reduced_by_server"] is False
    assert under["budget"]["effective_points"] == 5


def test_a_selection_over_the_work_ceiling_fails_with_a_code():
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=11)
    client = TestClient(create_app(RequestCoordinator(executor)))

    view = client.post("/api/v1/point-fields", json=BODY).json()

    assert view["state"] == "failed"
    assert view["failure"]["code"] == "work_limit"


@pytest.mark.parametrize("time", [
    "2026-01-02T00:00:00Z", "2026-01-02T00:00:00+00:00",
    "2026-01-02T05:30:00+05:30", "2026-01-02T00:00:00", "2026-01-02",
])
def test_every_spelling_of_the_same_utc_instant_selects_it(client, time):
    view = client.post("/api/v1/point-fields",
                       json={**BODY, "time": time}).json()

    assert view["state"] == "succeeded", view["failure"]


def test_unexpected_fields_are_refused(client):
    response = client.post("/api/v1/point-fields",
                           json={**BODY, "renderer": "three"})
    assert response.status_code == 422


def test_a_failed_build_is_reported_as_state_and_has_no_data(client):
    view = client.post("/api/v1/point-fields",
                       json={**BODY, "dataset_version_id": "import-404"}).json()

    assert view["state"] == "failed"
    assert view["failure"]["code"] == "data_unavailable"
    assert view["product"] is None
    data = client.get(view["links"]["data"])
    assert data.status_code == 409
    assert data.json()["detail"]["state"] == "failed"


def test_unknown_requests_are_not_found(client):
    assert client.get("/api/v1/point-fields/nope").status_code == 404
    assert client.get("/api/v1/point-fields/nope/data").status_code == 404


class QueuedExecutor(ProductExecutor):
    """A stand-in for a worker executor: accepts now, builds later."""

    def __init__(self) -> None:
        self.jobs: dict[str, ProductJob] = {}

    @property
    def capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(maximum_points=10, maximum_cells=1000,
                                    asynchronous=True,
                                    cancellation=True, supersession=True,
                                    status_shared_across_instances=True)

    def submit(self, request):
        job = ProductJob(request_id=f"q{len(self.jobs)}", request=request,
                         state=JobState.ACCEPTED, submitted_at="t0")
        self.jobs[job.request_id] = job
        return job

    def job(self, request_id):
        if request_id not in self.jobs:
            raise UnknownRequestError(request_id)
        return self.jobs[request_id]

    def finish(self, request_id):
        job = self.jobs[request_id]
        self.jobs[request_id] = replace(
            job, state=JobState.SUCCEEDED, finished_at="t1",
            product=fixtures.builder()(job.request))


def test_another_executor_plugs_in_without_changing_the_http_surface():
    executor = QueuedExecutor()
    client = TestClient(create_app(RequestCoordinator(executor)))

    view = client.post("/api/v1/point-fields", json=BODY).json()
    assert view["state"] == "accepted" and view["finished"] is False
    early = client.get(view["links"]["data"])
    assert early.status_code == 409
    assert early.json()["detail"]["state"] == "accepted"

    executor.finish(view["request_id"])
    assert client.get(view["links"]["data"]).status_code == 200
    assert client.get("/api/v1/capabilities").json()["executor"][
        "asynchronous"] is True


def test_composition_reads_its_limits_from_the_environment(monkeypatch):
    monkeypatch.setenv("SERVING_MAX_POINTS", "4")
    monkeypatch.setenv("SERVING_MAX_CELLS", "11")
    client = TestClient(compose.build_app(fixtures.builder()))

    executor = client.get("/api/v1/capabilities").json()["executor"]
    assert executor["maximum_points"] == 4
    assert executor["maximum_cells"] == 11
    monkeypatch.setenv("SERVING_MAX_POINTS", "many")
    with pytest.raises(ValueError, match="SERVING_MAX_POINTS"):
        compose.build_app(fixtures.builder())


def test_serving_loads_only_the_s3_contract_never_storage_or_config():
    # S5 reads S3 through its query contract (ingestion.query) and nothing
    # else: no storage adapter, driver, configuration or composition.
    probe = ("import sys, serving.compose; "
             "bad = sorted(m for m in sys.modules if m == 'psycopg' "
             "or m.startswith(('psycopg.', 'ingestion.storage', "
             "'ingestion.config', 'ingestion.composition', "
             "'ingestion.adapters', 'ingestion.web', 'ingestion.service'))); "
             "print(bad)")
    result = subprocess.run([sys.executable, "-c", probe], check=True,
                            capture_output=True, text=True)

    assert result.stdout.strip() == "[]"


@dataclass(frozen=True)
class _Version:
    id: str
    variables: tuple[str, ...]


class _Catalogue:
    def __init__(self, versions=(), fail=False, observations_fail=False):
        self.versions, self.fail = versions, fail
        self.observations_fail = observations_fail

    def list_model_versions(self):
        if self.fail:
            raise RuntimeError("postgresql://secret@db/incois is down")
        if isinstance(self.versions, DatasetVersionListing):
            return self.versions
        return DatasetVersionListing(versions=tuple(self.versions), unavailable=())

    def list_observation_versions(self):
        if self.observations_fail:
            raise RuntimeError("postgresql://secret@db/incois is down")
        return ObservationVersionListing(versions=(), unavailable=())


def _app(catalogue=None, web_root=None):
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    return TestClient(create_app(RequestCoordinator(executor), catalogue,
                                 web_root))


def test_the_catalogue_lists_versions_as_plain_json():
    client = _app(_Catalogue((_Version("import-1", ("water_temp",)),)))

    assert client.get("/api/v1/catalogue").json() == {
        "versions": [{"id": "import-1", "variables": ["water_temp"]}],
        "unavailable": [],
        "observation_versions": [],
        "observation_unavailable": [],
        "observation_failure": None}


def test_an_observation_outage_is_a_coded_partial_failure():
    catalogue = _Catalogue((_Version("import-1", ("water_temp",)),),
                           observations_fail=True)
    response = _app(catalogue).get("/api/v1/catalogue")

    assert response.status_code == 200
    body = response.json()
    assert [v["id"] for v in body["versions"]] == ["import-1"]
    assert body["observation_versions"] is None
    assert body["observation_failure"]["code"] == "observation_catalogue_unavailable"
    assert "secret" not in response.text


def test_the_catalogue_reports_versions_it_could_not_read():
    listing = DatasetVersionListing(
        versions=(), unavailable=(UnavailableDatasetVersion("import-9", "the stored object could not be opened"),))
    body = _app(_Catalogue(listing)).get("/api/v1/catalogue").json()

    assert body["unavailable"] == [{"id": "import-9", "reason": "the stored object could not be opened"}]


@pytest.mark.parametrize("catalogue", [None, _Catalogue(fail=True)])
def test_an_unavailable_catalogue_is_reported_without_detail(catalogue):
    response = _app(catalogue).get("/api/v1/catalogue")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "catalogue_unavailable"
    assert "secret" not in response.text


def test_the_browser_app_is_served_from_the_same_origin(tmp_path):
    (tmp_path / "index.html").write_text("<title>ocean</title>")
    client = _app(web_root=tmp_path)

    assert "ocean" in client.get("/").text
    assert client.get("/api/v1/capabilities").status_code == 200


def test_the_default_app_binds_the_configured_s3_reads(monkeypatch):
    monkeypatch.setenv("S3_QUERY_BACKEND", "memory")
    monkeypatch.setenv("SERVING_WEB_ROOT", "")
    client = TestClient(compose.create_default_app())

    assert client.get("/api/v1/catalogue").json()["versions"] == []
    view = client.post("/api/v1/point-fields", json=BODY).json()
    assert view["failure"]["code"] == "data_unavailable"
