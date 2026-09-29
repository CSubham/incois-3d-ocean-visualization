"""S5 slice serving: one horizontal level of a model field, scalar or vector.

Like observations, a slice of an immutable stored version is bounded work
and a pure function of its request, so it takes the synchronous path and
keeps no job state. Transport-neutral; the HTTP adapter translates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from processing import (
    DepthSliceProduct, DepthSliceSelection, Failure, GeographicBounds,
    InvalidRequestError, ProcessingError, ProductBuilder, VectorSliceProduct,
    failure_for,
)
from processing.managed import (
    ManagedDepthSliceRequest, ManagedVectorSliceRequest,
)
from serving.coordinator import RequestRejected, _instant

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SliceWindow:
    """Where and when: one time, one depth, one geographic box."""

    dataset_version_id: str
    time: str
    depth: float
    west: float
    east: float
    south: float
    north: float


class SliceFailed(Exception):
    """A valid request whose slice could not be prepared."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class SliceService:
    def __init__(
        self,
        scalar: ProductBuilder[ManagedDepthSliceRequest, DepthSliceProduct],
        vector: ProductBuilder[ManagedVectorSliceRequest, VectorSliceProduct],
        maximum_cells: int,
    ) -> None:
        self._scalar = scalar
        self._vector = vector
        self._maximum_cells = maximum_cells

    def scalar(self, window: SliceWindow, variable: str) -> DepthSliceProduct:
        request = self._request(lambda: ManagedDepthSliceRequest(
            window.dataset_version_id, self._selection(window, variable),
            self._maximum_cells))
        return self._run(self._scalar, request)

    def vector(self, window: SliceWindow, eastward: str,
               northward: str) -> VectorSliceProduct:
        request = self._request(lambda: ManagedVectorSliceRequest(
            window.dataset_version_id,
            eastward=self._selection(window, eastward),
            northward=self._selection(window, northward),
            maximum_cells=self._maximum_cells))
        return self._run(self._vector, request)

    @staticmethod
    def _selection(window: SliceWindow, variable: str) -> DepthSliceSelection:
        return DepthSliceSelection(
            variable=variable, time=_instant(window.time),
            area=GeographicBounds(west=window.west, east=window.east,
                                  south=window.south, north=window.north),
            depth=window.depth)

    @staticmethod
    def _request(build: Any) -> Any:
        try:
            return build()
        except (InvalidRequestError, ProcessingError, ValueError) as exc:
            raise RequestRejected("invalid_request", str(exc)) from exc

    @staticmethod
    def _run(builder: Any, request: Any) -> Any:
        try:
            return builder(request)
        except Exception as exc:  # every failure becomes a coded answer
            failure = failure_for(exc)
            if failure.code == "internal_error":
                log.exception("slice product failed")
            raise SliceFailed(failure) from exc
