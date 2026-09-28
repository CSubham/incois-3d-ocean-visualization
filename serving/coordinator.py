"""The S5 request coordinator: browser intent in, prepared products out.

Transport-neutral. The HTTP adapter translates to and from it, and so would
any other entry point. It validates what a client asked for, submits it
through the configured S4 executor, and exposes state, failure and the
finished product -- never a renderer object and never a storage detail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from processing import (
    DepthBounds, ExecutorCapabilities, GeographicBounds, InvalidRequestError,
    JobState, ProductExecutor, ProductJob, ProductRequest, SamplingRequest,
    ScalarPointFieldProduct, ScalarSelection, UnknownRequestError,
    failure_for,
)


class RequestRejected(Exception):
    """The client's request is invalid and was never submitted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UnknownRequest(Exception):
    """No such request is known here."""


class ProductNotReady(Exception):
    """The request exists but has no product to deliver."""

    def __init__(self, job: ProductJob) -> None:
        super().__init__(f"request {job.request_id} is {job.state.value}")
        self.job = job


@dataclass(frozen=True)
class PointFieldIntent:
    """What a client may ask for, before it is turned into domain objects."""

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


def _instant(text: str) -> np.datetime64:
    """An ISO 8601 instant as naive UTC, the form decoded source times take.

    An explicit offset is converted, not refused: the catalogue itself writes
    UTC as ``+00:00``. A time without an offset is taken as UTC.
    """
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise RequestRejected(
            "invalid_request", f"time {text!r} is not an ISO 8601 instant"
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return np.datetime64(parsed, "ns")


class RequestCoordinator:
    def __init__(self, executor: ProductExecutor) -> None:
        self._executor = executor

    @property
    def capabilities(self) -> ExecutorCapabilities:
        return self._executor.capabilities

    def request_point_field(self, intent: PointFieldIntent) -> ProductJob:
        """Submit a request under the effective point budget.

        ``intent.maximum_points`` is what the client can display, or its
        retry budget after a resource fallback. The effective budget is the
        smaller of that and the server ceiling; a reduction is recorded on the
        request rather than refused, so the client can disclose it.
        """
        ceiling = self._executor.capabilities.maximum_points
        effective = min(intent.maximum_points, ceiling)
        try:
            request = ProductRequest(
                dataset_version_id=intent.dataset_version_id,
                selection=ScalarSelection(
                    variable=intent.variable,
                    time=_instant(intent.time),
                    area=GeographicBounds(west=intent.west, east=intent.east,
                                          south=intent.south,
                                          north=intent.north),
                    depth=DepthBounds(minimum=intent.depth_minimum,
                                      maximum=intent.depth_maximum),
                ),
                sampling=SamplingRequest(maximum_points=effective),
                requested_maximum_points=intent.maximum_points,
            )
            return self._executor.submit(request)
        except InvalidRequestError as exc:
            failure = failure_for(exc)
            raise RequestRejected(failure.code, failure.message) from exc

    def job(self, request_id: str) -> ProductJob:
        try:
            return self._executor.job(request_id)
        except UnknownRequestError as exc:
            raise UnknownRequest(str(exc)) from exc

    def product(self, request_id: str) -> ScalarPointFieldProduct:
        job = self.job(request_id)
        if job.state is not JobState.SUCCEEDED or job.product is None:
            raise ProductNotReady(job)
        return job.product
