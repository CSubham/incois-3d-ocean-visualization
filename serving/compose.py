"""The S5 composition point: the one place that picks implementations.

Configured by environment. Core modules receive what is built here and never
choose for themselves, so a worker executor or another entry adapter replaces
one line here rather than a branch inside the workflow.

`build_app` takes the product builder and catalogue explicitly, for tests
and alternative bindings. `create_default_app` binds both to the configured
S3 reads; it is the deployable entry point:

    uvicorn serving.compose:create_default_app --factory

Storage modules are imported only inside it, so importing this module loads
no storage driver.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from processing import LocalExecutor, ProductBuilder
from serving.coordinator import RequestCoordinator
from serving.http import Catalogue, create_app

if TYPE_CHECKING:
    from serving.observations import ObservationService

#: The built browser app, served from the same origin when present.
DEFAULT_WEB_ROOT = Path(__file__).resolve().parents[1] / "web" / "dist"

#: Server-side ceilings. They protect the service; neither is a tested
#: browser budget, which S6 owns. Five million float32 cells is about 20 MB.
DEFAULT_MAXIMUM_POINTS = 500_000
DEFAULT_MAXIMUM_CELLS = 5_000_000
#: Markers per request. Each marker's product reads its full profile record.
DEFAULT_MAXIMUM_MARKERS = 2_000


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, not {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be positive, not {value}")
    return value


def _web_root() -> Path | None:
    raw = os.environ.get("SERVING_WEB_ROOT")
    if raw is not None:
        return Path(raw) if raw.strip() else None
    return DEFAULT_WEB_ROOT if DEFAULT_WEB_ROOT.is_dir() else None


def build_app(builder: ProductBuilder,
              catalogue: Catalogue | None = None,
              observations: ObservationService | None = None) -> FastAPI:
    executor = LocalExecutor(
        builder,
        maximum_points=_positive_int("SERVING_MAX_POINTS",
                                     DEFAULT_MAXIMUM_POINTS),
        maximum_cells=_positive_int("SERVING_MAX_CELLS",
                                    DEFAULT_MAXIMUM_CELLS),
        retained_jobs=_positive_int("SERVING_RETAINED_JOBS", 256),
    )
    return create_app(RequestCoordinator(executor), catalogue, _web_root(),
                      observations)


def create_default_app() -> FastAPI:
    """The deployable app: product builder and catalogue over S3 reads."""
    from ingestion.composition import build_model_field_query
    from processing.managed import (
        managed_observation_marker_builder, managed_observation_profile_builder,
        managed_point_field_builder,
    )
    from serving.observations import ObservationService

    query = build_model_field_query()
    observations = ObservationService(
        markers=managed_observation_marker_builder(
            query, maximum_markers=_positive_int(
                "SERVING_MAX_MARKERS", DEFAULT_MAXIMUM_MARKERS)),
        profiles=managed_observation_profile_builder(query),
    )
    return build_app(managed_point_field_builder(query), catalogue=query,
                     observations=observations)
