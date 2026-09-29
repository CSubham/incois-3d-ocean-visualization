"""Surface temperature and current-vector slices over HTTP, on the S3 fake."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ingestion.query import VariableSummary
from ingestion.query_memory import InMemoryModelFieldQuery
from ingestion.tests.query_support import MODEL_VERSION_ID, in_memory_case
from processing import LocalExecutor
from processing.managed import (
    managed_depth_slice_builder, managed_vector_slice_builder,
)
from processing.tests import fixtures
from serving import wire_slice, wire_vector
from serving.coordinator import RequestCoordinator
from serving.http import create_app
from serving.slices import SliceService

WINDOW = {"dataset_version_id": MODEL_VERSION_ID, "time": "2026-09-28T00:00:00Z",
          "depth": 0.0, "west": 70, "east": 80, "south": 5, "north": 12}
VECTOR = {**WINDOW, "eastward": "water_u", "northward": "water_v"}


def _query_with_currents() -> InMemoryModelFieldQuery:
    """The fixture version plus u = 3 and v = 4 m/s, one cell missing in v."""
    query = in_memory_case().query
    assert isinstance(query, InMemoryModelFieldQuery)
    version = query._versions[MODEL_VERSION_ID]
    dataset = version.dataset.copy()
    shape = dataset["water_temp"].shape
    u = np.full(shape, 3.0, dtype=np.float32)
    v = np.full(shape, 4.0, dtype=np.float32)
    v[0, 0, 1, 3] = np.nan
    dims = dataset["water_temp"].dims
    dataset["water_u"] = (dims, u, {"units": "m/s",
                                    "standard_name": "eastward_sea_water_velocity"})
    dataset["water_v"] = (dims, v, {"units": "m/s",
                                    "standard_name": "northward_sea_water_velocity"})
    base = version.descriptors["water_temp"]
    descriptors = {
        **version.descriptors,
        "water_u": replace(base, variable="water_u", units="m/s",
                           standard_name="eastward_sea_water_velocity"),
        "water_v": replace(base, variable="water_v", units="m/s",
                           standard_name="northward_sea_water_velocity"),
    }
    summary = replace(version.summary, variables=(
        *version.summary.variables,
        VariableSummary("water_u", "m/s"), VariableSummary("water_v", "m/s")))
    return InMemoryModelFieldQuery([replace(
        version, summary=summary, dataset=dataset, descriptors=descriptors)])


def _client(query=None, slices=True) -> TestClient:
    query = query or _query_with_currents()
    service = SliceService(scalar=managed_depth_slice_builder(query),
                           vector=managed_vector_slice_builder(query),
                           maximum_cells=1000) if slices else None
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    return TestClient(create_app(RequestCoordinator(executor), slices=service))


def test_a_surface_temperature_slice_is_described_then_fetched_exactly():
    client = _client()
    described = client.get("/api/v1/depth-slices",
                           params={**WINDOW, "variable": "water_temp"})
    assert described.status_code == 200
    body = described.json()
    assert body["wire_format"] == wire_slice.WIRE_FORMAT
    assert body["grid_shape"] == [2, 4]
    assert body["product"]["interpolation"]["delivered_depth"] == 0.0

    data = client.get(body["data"]["url"])
    arrays = wire_slice.decode(body["data"]["arrays"], data.content)
    # Arrays travel flat, row-major over grid_shape (latitude, longitude).
    assert np.array_equal(arrays["values"], np.arange(8, dtype=np.float32) + 20.0)
    assert arrays["missing_value_mask"].sum() == 0


def test_a_current_slice_carries_both_components_and_their_speed():
    client = _client()
    body = client.get("/api/v1/vector-slices", params=VECTOR).json()
    assert body["wire_format"] == wire_vector.WIRE_FORMAT
    assert body["product"]["units"] == "m/s"
    assert body["product"]["speed_range"]["maximum"] == 5.0

    arrays = wire_vector.decode(body["data"]["arrays"],
                                client.get(body["data"]["url"]).content)
    assert np.all(arrays["eastward"] == 3.0)
    missing = arrays["missing_value_mask"].reshape(2, 4)
    assert missing[1, 3] == 1 and missing.sum() == 1
    assert np.isnan(arrays["speed"].reshape(2, 4)[1, 3])
    speed = arrays["speed"][arrays["missing_value_mask"] == 0]
    assert np.allclose(speed, 5.0)


def test_components_in_different_units_are_refused():
    response = _client().get("/api/v1/vector-slices", params={
        **VECTOR, "eastward": "water_temp", "northward": "salinity"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_grid"


@pytest.mark.parametrize("params, status, code", [
    ({**WINDOW, "variable": "absent"}, 404, "variable_unavailable"),
    ({**WINDOW, "variable": "water_temp", "time": "yesterday"}, 400, "invalid_request"),
    ({**WINDOW, "variable": "water_temp", "depth": 5.0}, 404, "depth_unavailable"),
])
def test_slice_failures_are_coded(params, status, code):
    response = _client().get("/api/v1/depth-slices", params=params)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_the_same_component_twice_is_not_a_vector():
    response = _client().get("/api/v1/vector-slices", params={
        **VECTOR, "northward": "water_u"})
    assert response.status_code == 400


def test_without_a_slice_service_the_routes_say_so():
    response = _client(slices=False).get(
        "/api/v1/depth-slices", params={**WINDOW, "variable": "water_temp"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "slices_unavailable"
