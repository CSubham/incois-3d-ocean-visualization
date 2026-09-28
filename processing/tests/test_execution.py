"""The S4 execution contract and its local executor."""

from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from processing import (
    AllMissingSubsetError, EmptySubsetError, GridValidationError,
    InvalidRequestError, JobState, LocalExecutor, ManagedDataUnavailableError,
    PointBudgetError, ProductRequest, TimeSelectionError, UnknownRequestError,
    VariableSelectionError, WorkLimitError,
)
from processing.tests import fixtures


def test_a_bounded_request_is_built_before_submit_returns():
    job = LocalExecutor(fixtures.builder(), maximum_points=100,
                        maximum_cells=1000).submit(
        fixtures.request(maximum_points=5))

    assert job.state is JobState.SUCCEEDED
    assert job.state.finished
    assert job.product.sampling.delivered_point_count == 5
    assert job.failure is None
    assert job.submitted_at <= job.finished_at


def test_the_builder_receives_the_request_with_the_work_ceiling_applied():
    seen = []
    executor = LocalExecutor(lambda request: seen.append(request) or
                             fixtures.builder()(request),
                             maximum_points=100, maximum_cells=1000)
    submitted = fixtures.request()

    job = executor.submit(submitted)

    assert seen == [replace(submitted, maximum_cells=1000)]
    assert job.request.maximum_cells == 1000


def test_a_finished_job_can_be_read_back_by_its_identity():
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    job = executor.submit(fixtures.request())

    assert executor.job(job.request_id) == job


@pytest.mark.parametrize("error, code", [
    (PointBudgetError("x"), "point_budget"),
    (InvalidRequestError("x"), "invalid_request"),
    (VariableSelectionError("x"), "variable_unavailable"),
    (TimeSelectionError("x"), "time_unavailable"),
    (GridValidationError("x"), "unsupported_grid"),
    (EmptySubsetError("x"), "empty_subset"),
    (AllMissingSubsetError("x"), "all_missing"),
    (ManagedDataUnavailableError("x"), "data_unavailable"),
    (WorkLimitError("x"), "work_limit"),
])
def test_each_processing_failure_becomes_a_stable_code(error, code):
    def fail(_request):
        raise error

    job = LocalExecutor(fail, maximum_points=100,
                        maximum_cells=1000).submit(fixtures.request())

    assert job.state is JobState.FAILED
    assert job.failure.code == code
    assert job.failure.message == "x"
    assert job.product is None


def test_an_unexpected_failure_is_logged_but_not_leaked(caplog):
    def fail(_request):
        raise RuntimeError("password=hunter2 at /srv/objects/secret.nc")

    with caplog.at_level(logging.ERROR, logger="processing.execution"):
        job = LocalExecutor(fail, maximum_points=100,
                            maximum_cells=1000).submit(fixtures.request())

    assert job.failure.code == "internal_error"
    assert "hunter2" not in job.failure.message
    assert "/srv/objects" not in job.failure.message
    assert "hunter2" in caplog.text


def test_a_request_over_the_executor_limit_is_refused_before_any_work():
    calls = []
    executor = LocalExecutor(lambda request: calls.append(request),
                             maximum_points=4, maximum_cells=1000)

    with pytest.raises(PointBudgetError, match="limit of 4"):
        executor.submit(fixtures.request(maximum_points=5))
    assert calls == []


def test_an_unknown_request_identity_is_a_typed_error():
    with pytest.raises(UnknownRequestError, match="nope"):
        LocalExecutor(fixtures.builder(), maximum_points=10,
                      maximum_cells=1000).job("nope")


def test_only_the_most_recent_jobs_are_retained():
    executor = LocalExecutor(fixtures.builder(), maximum_points=10,
                             maximum_cells=1000, retained_jobs=2)
    first, second, third = (executor.submit(fixtures.request())
                            for _ in range(3))

    with pytest.raises(UnknownRequestError):
        executor.job(first.request_id)
    assert executor.job(second.request_id) == second
    assert executor.job(third.request_id) == third


def test_the_local_executor_declares_what_it_cannot_do():
    capabilities = LocalExecutor(fixtures.builder(),
                                 maximum_points=7,
                                 maximum_cells=1000).capabilities

    assert capabilities.maximum_points == 7
    assert capabilities.maximum_cells == 1000
    assert capabilities.asynchronous is False
    assert capabilities.cancellation is False
    assert capabilities.supersession is False
    assert capabilities.status_shared_across_instances is False


def test_a_request_must_name_a_dataset_version():
    with pytest.raises(InvalidRequestError, match="dataset_version_id"):
        ProductRequest(dataset_version_id=" ",
                       selection=fixtures.request().selection,
                       sampling=fixtures.request().sampling)


def test_the_work_ceiling_refuses_an_oversized_selection():
    job = LocalExecutor(fixtures.builder(), maximum_points=100,
                        maximum_cells=11).submit(fixtures.request())

    assert job.state is JobState.FAILED
    assert job.failure.code == "work_limit"
    assert "12 cells" in job.failure.message


def test_a_request_may_ask_for_a_lower_work_ceiling_but_not_a_higher_one():
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=50)

    lower = executor.submit(replace(fixtures.request(), maximum_cells=20))
    higher = executor.submit(replace(fixtures.request(), maximum_cells=10**9))

    assert lower.request.maximum_cells == 20
    assert higher.request.maximum_cells == 50


def test_a_product_from_a_builder_that_ignored_the_ceiling_is_not_served():
    def careless(request):
        return fixtures.builder()(replace(request, maximum_cells=None))

    job = LocalExecutor(careless, maximum_points=100,
                        maximum_cells=11).submit(fixtures.request())

    assert job.state is JobState.FAILED
    assert job.failure.code == "work_limit"
    assert job.product is None


def test_an_effective_budget_cannot_exceed_the_requested_one():
    with pytest.raises(InvalidRequestError, match="cannot exceed"):
        replace(fixtures.request(maximum_points=5), requested_maximum_points=4)
    reduced = replace(fixtures.request(maximum_points=5),
                      requested_maximum_points=9)
    assert reduced.budget_reduced is True
    assert fixtures.request().budget_reduced is False


def test_a_job_that_finishes_late_cannot_evict_a_newer_request():
    import threading

    release, started = threading.Event(), threading.Event()

    def builder(request):
        if request.sampling.maximum_points == 7:
            started.set()
            release.wait(5)
        return fixtures.builder()(request)

    executor = LocalExecutor(builder, maximum_points=100, maximum_cells=1000,
                             retained_jobs=2)
    slow: dict = {}
    worker = threading.Thread(target=lambda: slow.setdefault(
        "job", executor.submit(fixtures.request(maximum_points=7))))
    worker.start()
    started.wait(5)
    newer = executor.submit(fixtures.request(maximum_points=5))
    newest = executor.submit(fixtures.request(maximum_points=5))
    release.set()
    worker.join()

    assert executor.job(newer.request_id) == newer
    assert executor.job(newest.request_id) == newest
    with pytest.raises(UnknownRequestError):
        executor.job(slow["job"].request_id)
