"""The S4 execution boundary: one contract, replaceable executors.

S5 submits a validated product request and later asks for its state. Where
the work runs -- in this process, a local worker, a remote queue -- is the
executor's business. The request, state, result and failure semantics are the
same for every executor, and each declares up front what it cannot do
(cancel, supersede, share status across instances) rather than failing at it.

The product is built by an injected builder, bound at the composition point to
the configured storage read path. Nothing here knows where data lives.
"""

from __future__ import annotations

import logging
import threading
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol, TypeVar

from processing.domain import (
    SamplingRequest, ScalarPointFieldProduct, ScalarSelection,
)
from processing.errors import (
    AllMissingSubsetError, DepthSelectionError, EmptySubsetError,
    GridValidationError, InvalidRequestError, ManagedDataUnavailableError,
    PointBudgetError, TimeSelectionError, UnknownRequestError,
    VariableSelectionError, WorkLimitError,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductRequest:
    """One point-field product for one stored dataset version.

    ``sampling.maximum_points`` is the effective budget. When a caller
    reduced what the client asked for, ``requested_maximum_points`` keeps the
    original so the reduction can be disclosed. ``maximum_cells`` is the work
    ceiling the executor applies; a builder must pass it to the subsetter.
    """

    dataset_version_id: str
    selection: ScalarSelection
    sampling: SamplingRequest
    requested_maximum_points: Optional[int] = None
    maximum_cells: Optional[int] = None

    def __post_init__(self) -> None:
        if (not isinstance(self.dataset_version_id, str)
                or not self.dataset_version_id.strip()):
            raise InvalidRequestError("a dataset_version_id is required")
        requested = self.requested_maximum_points
        if requested is not None and requested < self.sampling.maximum_points:
            raise InvalidRequestError(
                "the effective point budget cannot exceed what was requested")
        if self.maximum_cells is not None and self.maximum_cells < 1:
            raise InvalidRequestError("maximum_cells must be positive")

    @property
    def budget_reduced(self) -> bool:
        return (self.requested_maximum_points is not None
                and self.requested_maximum_points
                > self.sampling.maximum_points)


RequestT = TypeVar("RequestT", contravariant=True)
ProductT = TypeVar("ProductT", covariant=True)


class ProductBuilder(Protocol[RequestT, ProductT]):
    """Build one product from a transport-neutral request.

    Composition binds implementations to S3 reads. Concrete executors narrow
    this generic callable to the request and product families they support.
    """

    def __call__(self, request: RequestT) -> ProductT:
        """Build the requested product or raise a typed processing failure."""


class JobState(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def finished(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED)


@dataclass(frozen=True)
class Failure:
    """A stable code a client can branch on, plus a message a person can act on."""

    code: str
    message: str


#: Most specific first: PointBudgetError is an InvalidRequestError.
_FAILURE_CODES: tuple[tuple[type[Exception], str], ...] = (
    (PointBudgetError, "point_budget"),
    (WorkLimitError, "work_limit"),
    (InvalidRequestError, "invalid_request"),
    (VariableSelectionError, "variable_unavailable"),
    (TimeSelectionError, "time_unavailable"),
    (DepthSelectionError, "depth_unavailable"),
    (GridValidationError, "unsupported_grid"),
    (EmptySubsetError, "empty_subset"),
    (AllMissingSubsetError, "all_missing"),
    (ManagedDataUnavailableError, "data_unavailable"),
)


def failure_for(exc: Exception) -> Failure:
    """Translate a build failure without leaking what the caller cannot use."""
    for kind, code in _FAILURE_CODES:
        if isinstance(exc, kind):
            return Failure(code=code, message=str(exc))
    return Failure(code="internal_error",
                   message="the product could not be prepared; the failure "
                           "was logged for the operator")


@dataclass(frozen=True)
class ProductJob:
    """A snapshot of one request. Never updated in place."""

    request_id: str
    request: ProductRequest
    state: JobState
    submitted_at: str
    finished_at: Optional[str] = None
    product: Optional[ScalarPointFieldProduct] = None
    failure: Optional[Failure] = None


@dataclass(frozen=True)
class ExecutorCapabilities:
    """What an executor can and cannot do, declared rather than discovered."""

    maximum_points: int
    maximum_cells: int
    asynchronous: bool
    cancellation: bool
    supersession: bool
    status_shared_across_instances: bool


class ProductExecutor(ABC):
    """The S5 to S4 boundary."""

    @property
    @abstractmethod
    def capabilities(self) -> ExecutorCapabilities:
        """What this executor supports."""

    @abstractmethod
    def submit(self, request: ProductRequest) -> ProductJob:
        """Accept a request, or refuse it with PointBudgetError."""

    @abstractmethod
    def job(self, request_id: str) -> ProductJob:
        """The current state of a request, or UnknownRequestError."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalExecutor(ProductExecutor):
    """Builds each product in the calling thread before ``submit`` returns.

    For bounded work only. Job records live in this process and the oldest
    are forgotten beyond ``retained_jobs``, so behind more than one API
    instance a status request can reach an instance that never saw the job;
    the capabilities say so. A worker executor replaces this class and
    nothing else.
    """

    def __init__(self,
                 builder: ProductBuilder[ProductRequest,
                                         ScalarPointFieldProduct],
                 maximum_points: int,
                 maximum_cells: int, retained_jobs: int = 256) -> None:
        if min(maximum_points, maximum_cells, retained_jobs) < 1:
            raise ValueError("maximum_points, maximum_cells and retained_jobs "
                             "must be positive")
        self._builder = builder
        self._maximum_points = maximum_points
        self._maximum_cells = maximum_cells
        self._retained = retained_jobs
        self._jobs: OrderedDict[str, ProductJob] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def capabilities(self) -> ExecutorCapabilities:
        return ExecutorCapabilities(
            maximum_points=self._maximum_points,
            maximum_cells=self._maximum_cells,
            asynchronous=False,
            cancellation=False,
            supersession=False,
            status_shared_across_instances=False,
        )

    def submit(self, request: ProductRequest) -> ProductJob:
        wanted = request.sampling.maximum_points
        if wanted > self._maximum_points:
            raise PointBudgetError(
                f"maximum_points {wanted} exceeds this executor's limit of "
                f"{self._maximum_points}")
        cells = min(request.maximum_cells or self._maximum_cells,
                    self._maximum_cells)
        request = replace(request, maximum_cells=cells)

        job = ProductJob(request_id=uuid.uuid4().hex, request=request,
                         state=JobState.RUNNING, submitted_at=_now())
        self._keep(job, new=True)
        try:
            product = self._builder(request)
            built = product.sampling.original_point_count
            if built > cells:
                # The builder ignored the ceiling; the product is not served.
                raise WorkLimitError(
                    f"the product was built from {built} cells, above this "
                    f"server's limit of {cells}")
        except Exception as exc:  # every failure becomes a job state
            if failure_for(exc).code == "internal_error":
                log.exception("product build %s failed", job.request_id)
            job = replace(job, state=JobState.FAILED, finished_at=_now(),
                          failure=failure_for(exc))
        else:
            job = replace(job, state=JobState.SUCCEEDED, finished_at=_now(),
                          product=product)
        self._keep(job)
        return job

    def job(self, request_id: str) -> ProductJob:
        with self._lock:
            found = self._jobs.get(request_id)
        if found is None:
            raise UnknownRequestError(
                f"no request {request_id!r} is known to this executor")
        return found

    def _keep(self, job: ProductJob, *, new: bool = False) -> None:
        # Retention follows submission order. A finishing job only updates a
        # record still held; one already forgotten stays forgotten, so a job
        # that finishes late can never push out a newer request.
        with self._lock:
            if new:
                self._jobs[job.request_id] = job
                while len(self._jobs) > self._retained:
                    self._jobs.popitem(last=False)
            elif job.request_id in self._jobs:
                self._jobs[job.request_id] = job
