"""HTTP surface for the serving stage.

A thin translation layer over the request coordinator. Requests, state,
descriptors and failures travel as JSON on the control path; product arrays
travel as one binary body on a separate data path. Built by a factory so the
composition point decides what it is wired to.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from processing import JobState, ProductJob
from serving import wire
from serving.coordinator import (
    PointFieldIntent, ProductNotReady, RequestCoordinator, RequestRejected,
    UnknownRequest,
)

API = "/api/v1"


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


def create_app(coordinator: RequestCoordinator) -> FastAPI:
    app = FastAPI(title="Ocean data serving", version="1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "stage": "S5"}

    @app.get(f"{API}/capabilities")
    def capabilities() -> dict[str, Any]:
        return {"wire_format": wire.WIRE_FORMAT,
                "executor": asdict(coordinator.capabilities)}

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

    return app
