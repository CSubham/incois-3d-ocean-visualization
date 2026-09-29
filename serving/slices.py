"""S5 slice serving: one horizontal level of a model field, scalar or vector.

Like observations, a slice of an immutable stored version is bounded work
and a pure function of its request, so it takes the synchronous path and
keeps no job state. Because it is a pure function, the few most recent
products are kept: a descriptor request and its /data twin (and a replayed
animation step) are then built once. Transport-neutral; the HTTP adapter
translates.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
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
        maximum_display_cells: int = 2_000_000,
        display_side: int = 4096,
        retained_products: int = 16,
    ) -> None:
        self._scalar = scalar
        self._vector = vector
        #: Source cells read for one slice: protects the server.
        self._maximum_cells = maximum_cells
        #: Cells delivered for one view: a caller may ask for fewer, never more.
        self._maximum_display_cells = maximum_display_cells
        #: Longest delivered side, within every WebGL2 texture limit.
        self._display_side = display_side
        #: Recent scalar products by request; products are immutable.
        self._retained: OrderedDict[tuple[Any, ...], DepthSliceProduct] = OrderedDict()
        self._retained_limit = retained_products
        self._retained_lock = threading.Lock()

    def scalar(self, window: SliceWindow, variable: str,
               display_cells: int | None = None) -> DepthSliceProduct:
        """One level fitted to the view: ``display_cells`` is the caller's
        budget, capped by this server's; a larger slice is block-averaged."""
        if display_cells is not None and display_cells < 1:
            raise RequestRejected("invalid_request", "maximum_cells must be positive")
        budget = min(display_cells or self._maximum_display_cells,
                     self._maximum_display_cells)
        key = (window, variable, budget)
        with self._retained_lock:
            if key in self._retained:
                self._retained.move_to_end(key)
                return self._retained[key]
        request = self._request(lambda: ManagedDepthSliceRequest(
            window.dataset_version_id, self._selection(window, variable),
            maximum_cells=self._maximum_cells, display_cells=budget,
            display_side=self._display_side))
        product: DepthSliceProduct = self._run(self._scalar, request)
        with self._retained_lock:
            self._retained[key] = product
            while len(self._retained) > self._retained_limit:
                self._retained.popitem(last=False)
        return product

    def vector(self, window: SliceWindow, eastward: str,
               northward: str) -> VectorSliceProduct:
        request = self._request(lambda: ManagedVectorSliceRequest(
            window.dataset_version_id,
            eastward=self._selection(window, eastward),
            northward=self._selection(window, northward),
            maximum_cells=self._maximum_cells,
            display_cells=self._maximum_display_cells,
            display_side=self._display_side))
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
