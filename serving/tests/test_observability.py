"""Health probes, request ids and structured logs."""

from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from processing import LocalExecutor
from processing.tests import fixtures
from serving.coordinator import RequestCoordinator
from serving.http import create_app
from serving.observability import HEADER, JsonFormatter, configure_logging


def _client(readiness=()) -> TestClient:
    executor = LocalExecutor(fixtures.builder(), maximum_points=100,
                             maximum_cells=1000)
    return TestClient(create_app(RequestCoordinator(executor),
                                 readiness=readiness))


def test_liveness_ignores_dependencies():
    client = _client([("catalogue", lambda: "down")])

    assert client.get("/health/live").status_code == 200
    assert client.get("/health").status_code == 200


def test_readiness_reports_every_check():
    def broken():
        raise RuntimeError("postgresql://secret@db is down")

    client = _client([("catalogue", lambda: "schema 1 of 2"),
                      ("object_store", lambda: None), ("other", broken)])
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unready", "checks": {
        "catalogue": {"ready": False, "reason": "schema 1 of 2"},
        "object_store": {"ready": True, "reason": None},
        "other": {"ready": False, "reason": "the check itself failed"}}}
    assert "secret" not in response.text
    assert _client([("catalogue", lambda: None)]).get(
        "/health/ready").json()["status"] == "ready"


def test_a_safe_caller_request_id_is_kept_and_echoed():
    response = _client().get("/health", headers={HEADER: "trace-01.a_b"})
    assert response.headers[HEADER] == "trace-01.a_b"


def test_an_unsafe_or_missing_request_id_is_replaced():
    client = _client()
    unsafe = client.get("/health", headers={HEADER: "x" * 65})
    missing = client.get("/health")

    assert len(unsafe.headers[HEADER]) == 32
    assert missing.headers[HEADER] != unsafe.headers[HEADER]


def test_every_request_writes_one_access_line_with_its_id(caplog):
    with caplog.at_level(logging.INFO, logger="serving.access"):
        response = _client().get("/health", headers={HEADER: "abc"})

    [record] = [r for r in caplog.records if r.name == "serving.access"]
    line = json.loads(JsonFormatter().format(record))
    assert response.status_code == 200
    assert line["method"] == "GET" and line["path"] == "/health"
    assert line["status"] == 200 and line["duration_ms"] >= 0
    assert line["level"] == "INFO" and line["time"].endswith("Z")


def test_records_inside_a_request_carry_its_id(capsys):
    configure_logging("INFO")
    try:
        _client().get("/health", headers={HEADER: "req-7"})
        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    finally:
        root = logging.getLogger()
        root.handlers[:] = [h for h in root.handlers
                            if h.get_name() != "serving.stdout"]
    access = [line for line in lines if line["logger"] == "serving.access"]
    assert access and access[0]["request_id"] == "req-7"


def test_configuring_twice_installs_one_handler():
    root = logging.getLogger()
    try:
        configure_logging("INFO")
        configure_logging("WARNING", "text")
        assert sum(h.get_name() == "serving.stdout" for h in root.handlers) == 1
    finally:
        root.handlers[:] = [h for h in root.handlers
                            if h.get_name() != "serving.stdout"]
        root.setLevel(logging.WARNING)
