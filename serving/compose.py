"""The S5 composition point: the one place that picks implementations.

Configured by environment. Core modules receive what is built here and never
choose for themselves, so a worker executor or another entry adapter replaces
one line here rather than a branch inside the workflow.

The product builder is the binding to the storage read path. It is supplied
by the caller until that path exists (s3-query-contracts); then it is built
here from the same environment.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from processing import LocalExecutor, ProductBuilder
from serving.coordinator import RequestCoordinator
from serving.http import create_app

#: A server-side ceiling on points per product. It protects the service; it
#: is not a tested browser budget, which S6 owns.
DEFAULT_MAXIMUM_POINTS = 500_000


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


def build_app(builder: ProductBuilder) -> FastAPI:
    executor = LocalExecutor(
        builder,
        maximum_points=_positive_int("SERVING_MAX_POINTS",
                                     DEFAULT_MAXIMUM_POINTS),
        retained_jobs=_positive_int("SERVING_RETAINED_JOBS", 256),
    )
    return create_app(RequestCoordinator(executor))
