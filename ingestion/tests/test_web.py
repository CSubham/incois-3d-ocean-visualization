"""The HTTP surface. It translates; it must not decide anything."""

import pytest
from fastapi.testclient import TestClient

from ingestion import adapters
from ingestion.tests.fakes import GRID, UNREADABLE, FakeSource
from ingestion.web import app


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.setitem(adapters._BUILDERS, FakeSource.source_id, FakeSource)
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json()["stage"] == "S2"


def test_sources_expose_their_capabilities(client):
    sources = client.get("/api/sources").json()["sources"]
    fake = next(s for s in sources if s["source_id"] == FakeSource.source_id)
    assert fake["kind"] == "remote"
    assert fake["supports"]["depth_subsetting"] is True


def test_datasets_are_listed_for_a_source(client):
    found = client.get("/api/datasets",
                       params={"source_id": FakeSource.source_id}).json()
    assert {d["dataset_id"] for d in found["datasets"]} >= {GRID, UNREADABLE}


def test_an_unknown_source_is_not_found(client):
    response = client.get("/api/datasets", params={"source_id": "nope"})
    assert response.status_code == 404


def test_a_dataset_reports_variables_and_ranges(client):
    body = client.get("/api/dataset", params={
        "source_id": FakeSource.source_id, "dataset_id": GRID}).json()
    assert {v["name"] for v in body["variables"]} == {"temperature", "salinity"}
    assert {r["role"] for r in body["ranges"]} == {"vertical", "latitude"}


def test_import_returns_a_job_that_completes(client):
    job = client.post("/api/imports", json={
        "source_id": FakeSource.source_id, "dataset_id": GRID,
        "variables": ["temperature"],
        "depth": {"minimum": 0, "maximum": 50}}).json()

    assert job["ok"] is True, job["message"]
    assert job["result"]["geometry"] == "grid"
    assert job["receipt"]["reference"]

    polled = client.get(f"/api/imports/{job['import_id']}").json()
    assert polled["import_id"] == job["import_id"]
    assert polled["done"] is True


def test_a_rejected_import_reports_the_problems(client):
    job = client.post("/api/imports", json={
        "source_id": FakeSource.source_id, "dataset_id": UNREADABLE}).json()
    assert job["ok"] is False
    problems = job["result"]["validation"]["problems"]
    assert any("units" in p["detail"] for p in problems)


def test_unknown_import_is_not_found(client):
    assert client.get("/api/imports/nope").status_code == 404


def test_unexpected_fields_are_rejected(client):
    response = client.post("/api/imports", json={
        "source_id": FakeSource.source_id, "dataset_id": GRID, "sneaky": True})
    assert response.status_code == 422


def test_browsing_endpoints_are_gone(client):
    """Local file sources are archived; their endpoints went with them."""
    assert client.get("/api/browse",
                      params={"root_id": "data"}).status_code == 404
    assert client.get("/api/locations").status_code == 404
