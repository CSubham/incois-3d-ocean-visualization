"""S5 observation serving: markers and exact profiles.

Markers and existing profile records are bounded work on immutable stored
versions, so they take the synchronous path: each answer is a pure function
of its request, no job state is kept, and any number of API instances can
serve it. Transport-neutral; the HTTP adapter translates to and from it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ingestion.query import ProfileIdentity, ProfileSearch
from processing import Failure, InvalidRequestError, ProductBuilder, failure_for
from processing.managed import (
    ManagedObservationMarkerRequest, ManagedObservationProfileRequest,
)
from processing.observation import (
    ObservationMarkerProduct, ObservationProfileProduct,
)
from serving.coordinator import RequestRejected

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkerIntent:
    dataset_version_id: str
    west: float
    east: float
    south: float
    north: float
    time_start: str
    time_end: str


@dataclass(frozen=True)
class ProfileIntent:
    dataset_version_id: str
    platform_id: str
    cycle: str
    variables: tuple[str, ...]


class ObservationFailed(Exception):
    """A valid request whose product could not be prepared."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class ObservationService:
    def __init__(
        self,
        markers: ProductBuilder[ManagedObservationMarkerRequest,
                                ObservationMarkerProduct],
        profiles: ProductBuilder[ManagedObservationProfileRequest,
                                 ObservationProfileProduct],
    ) -> None:
        self._markers = markers
        self._profiles = profiles

    def markers(self, intent: MarkerIntent) -> ObservationMarkerProduct:
        try:
            request = ManagedObservationMarkerRequest(
                dataset_version_id=intent.dataset_version_id,
                search=ProfileSearch(
                    west=intent.west, east=intent.east,
                    south=intent.south, north=intent.north,
                    time_start=intent.time_start, time_end=intent.time_end))
        except (InvalidRequestError, ValueError) as exc:
            raise RequestRejected("invalid_request", str(exc)) from exc
        return self._run(self._markers, request)

    def profile(self, intent: ProfileIntent) -> ObservationProfileProduct:
        try:
            request = ManagedObservationProfileRequest(
                identity=ProfileIdentity(
                    dataset_version_id=intent.dataset_version_id,
                    platform_id=intent.platform_id, cycle=intent.cycle),
                variables=intent.variables)
        except (InvalidRequestError, ValueError) as exc:
            raise RequestRejected("invalid_request", str(exc)) from exc
        return self._run(self._profiles, request)

    @staticmethod
    def _run(builder: Any, request: Any) -> Any:
        try:
            return builder(request)
        except Exception as exc:  # every failure becomes a coded answer
            failure = failure_for(exc)
            if failure.code == "internal_error":
                log.exception("observation product failed")
            raise ObservationFailed(failure) from exc
