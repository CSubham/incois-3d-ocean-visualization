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

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from processing import JobState, ProductJob
from serving import wire
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


def create_app(coordinator: RequestCoordinator,
               catalogue: Catalogue | None = None,
               web_root: Path | None = None) -> FastAPI:
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
        return {"versions": [wire.plain(version) for version in versions],
                "unavailable": [wire.plain(item) for item in unavailable]}

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

    if web_root is not None:
        app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
    return app
