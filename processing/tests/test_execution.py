"""The S4 execution contract and its local executor."""

from __future__ import annotations

import logging

import pytest

from processing import (
    AllMissingSubsetError, EmptySubsetError, GridValidationError,
    InvalidRequestError, JobState, LocalExecutor, ManagedDataUnavailableError,
    PointBudgetError, ProductRequest, TimeSelectionError, UnknownRequestError,
    VariableSelectionError,
)
from processing.tests import fixtures


def test_a_bounded_request_is_built_before_submit_returns():
    job = LocalExecutor(fixtures.builder(), maximum_points=100).submit(
        fixtures.request(maximum_points=5))

    assert job.state is JobState.SUCCEEDED
    assert job.state.finished
    assert job.product.sampling.delivered_point_count == 5
    assert job.failure is None
    assert job.submitted_at <= job.finished_at


def test_the_builder_receives_the_request_unchanged():
    seen = []
    executor = LocalExecutor(lambda request: seen.append(request) or
                             fixtures.builder()(request), maximum_points=100)
    submitted = fixtures.request()

    executor.submit(submitted)

    assert seen == [submitted]


def test_a_finished_job_can_be_read_back_by_its_identity():
    executor = LocalExecutor(fixtures.builder(), maximum_points=100)
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
])
def test_each_processing_failure_becomes_a_stable_code(error, code):
    def fail(_request):
        raise error

    job = LocalExecutor(fail, maximum_points=100).submit(fixtures.request())

    assert job.state is JobState.FAILED
    assert job.failure.code == code
    assert job.failure.message == "x"
    assert job.product is None


def test_an_unexpected_failure_is_logged_but_not_leaked(caplog):
    def fail(_request):
        raise RuntimeError("password=hunter2 at /srv/objects/secret.nc")

    with caplog.at_level(logging.ERROR, logger="processing.execution"):
        job = LocalExecutor(fail, maximum_points=100).submit(fixtures.request())

    assert job.failure.code == "internal_error"
    assert "hunter2" not in job.failure.message
    assert "/srv/objects" not in job.failure.message
    assert "hunter2" in caplog.text


def test_a_request_over_the_executor_limit_is_refused_before_any_work():
    calls = []
    executor = LocalExecutor(lambda request: calls.append(request),
                             maximum_points=4)

    with pytest.raises(PointBudgetError, match="limit of 4"):
        executor.submit(fixtures.request(maximum_points=5))
    assert calls == []


def test_an_unknown_request_identity_is_a_typed_error():
    with pytest.raises(UnknownRequestError, match="nope"):
        LocalExecutor(fixtures.builder(), maximum_points=10).job("nope")


def test_only_the_most_recent_jobs_are_retained():
    executor = LocalExecutor(fixtures.builder(), maximum_points=10,
                             retained_jobs=2)
    first, second, third = (executor.submit(fixtures.request())
                            for _ in range(3))

    with pytest.raises(UnknownRequestError):
        executor.job(first.request_id)
    assert executor.job(second.request_id) == second
    assert executor.job(third.request_id) == third


def test_the_local_executor_declares_what_it_cannot_do():
    capabilities = LocalExecutor(fixtures.builder(),
                                 maximum_points=7).capabilities

    assert capabilities.maximum_points == 7
    assert capabilities.asynchronous is False
    assert capabilities.cancellation is False
    assert capabilities.supersession is False
    assert capabilities.status_shared_across_instances is False


def test_a_request_must_name_a_dataset_version():
    with pytest.raises(InvalidRequestError, match="dataset_version_id"):
        ProductRequest(dataset_version_id=" ",
                       selection=fixtures.request().selection,
                       sampling=fixtures.request().sampling)
