"""HTTP surface for the ingestion stage.

A thin translation layer: it turns requests into domain objects, calls the
application service, and renders what comes back. No ingestion logic lives
here, and nothing here knows what a source is made of.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ingestion.config import CATALOGUE_DSN, OBJECT_STORE_ROOT
from ingestion.domain.errors import (
    IngestionError, SelectionError, SourceError,
)
from ingestion.domain.selection import (
    Area, DepthRange, ImportSelection, TimeRange,
)
from ingestion.service import IngestionService
from ingestion.storage import LocalObjectStore, PostgresStorage

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Ocean data import", version="2.0")
service = IngestionService(
    storage=PostgresStorage(CATALOGUE_DSN, LocalObjectStore(OBJECT_STORE_ROOT)))


@app.middleware("http")
async def no_stale_frontend(request: Request, call_next):
    """Never let a browser hold on to an old copy of the interface.

    A cached script from a previous build calls endpoints that no longer
    exist, and the page then looks empty rather than broken -- which is far
    harder to diagnose than it is to prevent.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


# -- request bodies ---------------------------------------------------------

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RangeBody(Strict):
    start: Optional[str] = None
    end: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    west: Optional[float] = None
    east: Optional[float] = None
    south: Optional[float] = None
    north: Optional[float] = None


class ImportBody(Strict):
    source_id: str
    dataset_id: str
    variables: list[str] = Field(default_factory=list)
    time: Optional[RangeBody] = None
    depth: Optional[RangeBody] = None
    area: Optional[RangeBody] = None


# -- translation ------------------------------------------------------------

def _fail(exc: IngestionError) -> HTTPException:
    status = 400 if isinstance(exc, SelectionError) else 502
    if isinstance(exc, SourceError) and "unknown" in str(exc):
        status = 404
    return HTTPException(status_code=status, detail=str(exc))


def _selection(body: ImportBody) -> ImportSelection:
    time = (TimeRange(body.time.start, body.time.end)
            if body.time and body.time.start and body.time.end else None)
    depth = (DepthRange(body.depth.minimum, body.depth.maximum)
             if body.depth and body.depth.minimum is not None
             and body.depth.maximum is not None else None)
    area = (Area(west=body.area.west, east=body.area.east,
                 south=body.area.south, north=body.area.north)
            if body.area and None not in (body.area.west, body.area.east,
                                          body.area.south, body.area.north)
            else None)
    return ImportSelection(
        source_id=body.source_id, dataset_id=body.dataset_id,
        variables=tuple(body.variables), time=time, depth=depth, area=area)


# -- pages ------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": "S2"}


# -- choosing a source ------------------------------------------------------

@app.get("/api/sources")
def sources() -> dict[str, Any]:
    return {"sources": [
        {"source_id": d.source_id, "name": d.name, "kind": d.kind,
         "description": d.description, "needs_files": d.requires_user_files,
         "supports": {k: v for k, v in vars(d.capabilities).items()}}
        for d in service.sources()]}


# -- choosing a dataset -----------------------------------------------------

@app.get("/api/datasets")
def datasets(source_id: str) -> dict[str, Any]:
    try:
        found = service.datasets(source_id)
    except IngestionError as exc:
        raise _fail(exc) from exc
    return {"datasets": [
        {"dataset_id": d.dataset_id, "name": d.name,
         "description": d.description} for d in found]}


@app.get("/api/dataset")
def dataset(source_id: str, dataset_id: str) -> dict[str, Any]:
    try:
        metadata = service.inspect(source_id, dataset_id)
    except IngestionError as exc:
        raise _fail(exc) from exc
    return {
        "dataset_id": metadata.dataset_id,
        "name": metadata.name,
        "notes": list(metadata.notes),
        "variables": [
            {"name": v.name, "units": v.units,
             "description": v.long_name or v.standard_name or "",
             "dimensions": list(v.dimensions)} for v in metadata.variables],
        "ranges": [
            {"name": r.dimension, "role": r.role, "minimum": r.minimum,
             "maximum": r.maximum, "units": r.units, "count": r.count}
            for r in metadata.ranges],
        "details": metadata.attributes,
    }


# -- importing --------------------------------------------------------------

@app.post("/api/imports")
def start_import(body: ImportBody) -> dict[str, Any]:
    try:
        selection = _selection(body)
    except IngestionError as exc:
        raise _fail(exc) from exc
    job = service.start_import(selection)
    return job.describe()


@app.get("/api/imports/{import_id}")
def import_status(import_id: str) -> dict[str, Any]:
    job = service.job(import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such import")
    return job.describe()


@app.get("/api/imports")
def recent_imports() -> dict[str, Any]:
    return {"imports": [j.describe() for j in service.recent_jobs()]}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
