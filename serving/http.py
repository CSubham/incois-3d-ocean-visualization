"""HTTP surface for the serving stage.

A thin translation layer over the request coordinator. Requests, state,
descriptors and failures travel as JSON on the control path; product arrays
travel as one binary body on a separate data path. Built by a factory so the
composition point decides what it is wired to.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol, Sequence

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from processing import JobState, ProductJob
from serving import wire, wire_observation
from serving.observations import (
    MarkerIntent, ObservationFailed, ObservationService, ProfileIntent,
)
from serving.coordinator import (
    PointFieldIntent, ProductNotReady, RequestCoordinator, RequestRejected,
    UnknownRequest,
)

API = "/api/v1"

log = logging.getLogger(__name__)


class Catalogue(Protocol):
    """The S3 catalogue read S5 exposes. Entries are dataclasses."""

    def list_model_versions(self) -> Sequence[Any]: ...


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PointFieldBody(Strict):
    dataset_version_id: str
    variable: str
    time: str
    west: float
    east: float
    south: float
    north: float
    depth_minimum: float
    depth_maximum: float
    maximum_points: int


def _links(request_id: str) -> dict[str, str]:
    base = f"{API}/point-fields/{request_id}"
    return {"self": base, "data": f"{base}/data"}


def _view(job: ProductJob) -> dict[str, Any]:
    links = _links(job.request_id)
    request = job.request
    return {
        "request_id": job.request_id,
        "state": job.state.value,
        "finished": job.state.finished,
        "submitted_at": job.submitted_at,
        "finished_at": job.finished_at,
        "budget": {
            "requested_points": request.requested_maximum_points,
            "effective_points": request.sampling.maximum_points,
            "reduced_by_server": request.budget_reduced,
            "maximum_cells": request.maximum_cells,
        },
        "failure": asdict(job.failure) if job.failure else None,
        "product": (wire.describe(job.product, data_url=links["data"])
                    if job.state is JobState.SUCCEEDED and job.product
                    else None),
        "links": links,
    }


#: HTTP status for a failed observation product, by failure code.
_OBSERVATION_STATUS = {
    "point_budget": 400,
    "invalid_request": 400,
    "profile_not_found": 404,
    "variable_unavailable": 404,
    "time_unavailable": 404,
    "depth_unavailable": 404,
    "data_unavailable": 404,
    "unsupported_grid": 422,
    "empty_subset": 422,
    "invalid_observation": 422,
    "all_missing": 422,
    "work_limit": 422,
    "internal_error": 500,
}


def create_app(coordinator: RequestCoordinator,
               catalogue: Catalogue | None = None,
               web_root: Path | None = None,
               observations: ObservationService | None = None) -> FastAPI:
    """The HTTP surface. ``web_root``, when given, serves the browser app
    from the same origin, so no cross-origin access is ever opened."""
    app = FastAPI(title="Ocean data serving", version="1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "stage": "S5"}

    @app.get(f"{API}/capabilities")
    def capabilities() -> dict[str, Any]:
        return {"wire_format": wire.WIRE_FORMAT,
                "executor": asdict(coordinator.capabilities)}

    @app.get(f"{API}/catalogue")
    def model_catalogue() -> dict[str, Any]:
        if catalogue is None:
            raise HTTPException(status_code=503, detail={
                "code": "catalogue_unavailable",
                "message": "no catalogue is configured"})
        try:
            versions = catalogue.list_model_versions()
        except Exception as exc:
            log.exception("catalogue listing failed")
            raise HTTPException(status_code=503, detail={
                "code": "catalogue_unavailable",
                "message": "the model catalogue could not be read"}) from exc
        # Versions S3 could not read are reported, not silently omitted.
        unavailable = getattr(versions, "unavailable", ())
        body: dict[str, Any] = {
            "versions": [wire.plain(version) for version in versions],
            "unavailable": [wire.plain(item) for item in unavailable]}
        list_observations = getattr(catalogue, "list_observation_versions", None)
        if list_observations is not None:
            try:
                listing = list_observations()
            except Exception:
                log.exception("observation catalogue listing failed")
                body["observation_versions"] = None
                body["observation_unavailable"] = []
            else:
                body["observation_versions"] = [wire.plain(v) for v in listing]
                body["observation_unavailable"] = [
                    wire.plain(item) for item in getattr(listing, "unavailable", ())]
        return body

    @app.post(f"{API}/point-fields", status_code=202)
    def request_point_field(body: PointFieldBody) -> JSONResponse:
        try:
            job = coordinator.request_point_field(
                PointFieldIntent(**body.model_dump()))
        except RequestRejected as exc:
            raise HTTPException(status_code=400, detail={
                "code": exc.code, "message": exc.message}) from exc
        return JSONResponse(_view(job), status_code=202,
                            headers={"Location": _links(job.request_id)["self"]})

    @app.get(f"{API}/point-fields/{{request_id}}")
    def point_field(request_id: str) -> dict[str, Any]:
        try:
            return _view(coordinator.job(request_id))
        except UnknownRequest as exc:
            raise HTTPException(status_code=404, detail={
                "code": "unknown_request", "message": str(exc)}) from exc

    @app.get(f"{API}/point-fields/{{request_id}}/data")
    def point_field_data(request_id: str) -> Response:
        try:
            product = coordinator.product(request_id)
        except UnknownRequest as exc:
            raise HTTPException(status_code=404, detail={
                "code": "unknown_request", "message": str(exc)}) from exc
        except ProductNotReady as exc:
            raise HTTPException(status_code=409, detail={
                "code": "not_ready", "state": exc.job.state.value,
                "message": str(exc)}) from exc
        _, buffer = wire.encode(product)
        return Response(content=buffer, media_type=wire.MEDIA_TYPE,
                        headers={"X-Wire-Format": wire.WIRE_FORMAT})

    def _observed(prepare: Any) -> Any:
        if observations is None:
            raise HTTPException(status_code=503, detail={
                "code": "observations_unavailable",
                "message": "no observation service is configured"})
        try:
            return prepare(observations)
        except RequestRejected as exc:
            raise HTTPException(status_code=400, detail={
                "code": exc.code, "message": exc.message}) from exc
        except ObservationFailed as exc:
            failure = exc.failure
            raise HTTPException(
                status_code=_OBSERVATION_STATUS[failure.code],
                detail={"code": failure.code, "message": failure.message},
            ) from exc

    def _binary(product: Any) -> Response:
        _, buffer = wire_observation.encode(product)
        return Response(content=buffer, media_type=wire_observation.MEDIA_TYPE,
                        headers={"X-Wire-Format": wire_observation.WIRE_FORMAT})

    def _markers(dataset_version_id: str, west: float, east: float,
                 south: float, north: float, time_start: str, time_end: str):
        intent = MarkerIntent(dataset_version_id, west, east, south, north,
                              time_start, time_end)
        return _observed(lambda service: service.markers(intent))

    def _profile(dataset_version_id: str, platform_id: str, cycle: str,
                 variables: list[str]):
        intent = ProfileIntent(dataset_version_id, platform_id, cycle,
                               tuple(variables))
        return _observed(lambda service: service.profile(intent))

    # Stored versions never change, so each answer is a pure function of its
    # query string; the data URL repeats it rather than holding state.
    @app.get(f"{API}/observation-markers")
    def observation_markers(request: Request, dataset_version_id: str,
                            west: float, east: float, south: float,
                            north: float, time_start: str,
                            time_end: str) -> dict[str, Any]:
        product = _markers(dataset_version_id, west, east, south, north,
                           time_start, time_end)
        return wire_observation.describe(
            product, data_url=f"{API}/observation-markers/data?{request.url.query}")

    @app.get(f"{API}/observation-markers/data")
    def observation_markers_data(dataset_version_id: str, west: float,
                                 east: float, south: float, north: float,
                                 time_start: str, time_end: str) -> Response:
        return _binary(_markers(dataset_version_id, west, east, south, north,
                                time_start, time_end))

    @app.get(f"{API}/observation-profiles")
    def observation_profile(request: Request, dataset_version_id: str,
                            platform_id: str, cycle: str,
                            variables: list[str] = Query(...)) -> dict[str, Any]:
        product = _profile(dataset_version_id, platform_id, cycle, variables)
        return wire_observation.describe(
            product, data_url=f"{API}/observation-profiles/data?{request.url.query}")

    @app.get(f"{API}/observation-profiles/data")
    def observation_profile_data(dataset_version_id: str, platform_id: str,
                                 cycle: str,
                                 variables: list[str] = Query(...)) -> Response:
        return _binary(_profile(dataset_version_id, platform_id, cycle, variables))

    if web_root is not None:
        app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
    return app
