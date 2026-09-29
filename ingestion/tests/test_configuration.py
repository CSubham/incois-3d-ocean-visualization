"""Configuration: nothing defaulted that should not be, and no hangs."""

from __future__ import annotations

import time

import pytest

from ingestion.composition import build_model_field_query, build_readiness_checks
from ingestion.config import _seconds
from ingestion.domain.errors import ConfigurationError
from ingestion.query import ModelFieldQueryError
from ingestion.storage import LocalObjectStore
from ingestion.storage.postgres import PostgresStorage, StorageError
from ingestion.storage.query import CatalogueModelFieldQuery
from ingestion.tests.query_support import model_package

#: A non-routable address: a connection attempt can only time out.
BLACKHOLE = "postgresql://user:pass@10.255.255.1:5432/none"


def test_the_catalogue_backend_refuses_to_start_without_a_dsn(monkeypatch):
    monkeypatch.setattr("ingestion.composition.CATALOGUE_DSN", None)
    with pytest.raises(ConfigurationError, match="INGESTION_CATALOGUE_DSN is not set"):
        build_model_field_query(environ={"S3_QUERY_BACKEND": "catalogue"})


def test_an_import_without_a_catalogue_is_refused_before_any_array_is_written(tmp_path):
    storage = PostgresStorage(None, LocalObjectStore(tmp_path))

    with pytest.raises(StorageError, match="INGESTION_CATALOGUE_DSN is not set"):
        storage.hand_off(model_package())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("raw, message", [("soon", "whole number"), ("0", "at least 1")])
def test_bad_timeouts_are_refused(monkeypatch, raw, message):
    monkeypatch.setenv("SOME_TIMEOUT", raw)
    with pytest.raises(ValueError, match=message):
        _seconds("SOME_TIMEOUT", 5)


def test_an_unreachable_catalogue_fails_within_the_timeout(tmp_path):
    query = CatalogueModelFieldQuery(BLACKHOLE, LocalObjectStore(tmp_path), {},
                                     connect_timeout=1)
    started = time.monotonic()
    with pytest.raises(ModelFieldQueryError):
        query.list_model_versions()
    assert time.monotonic() - started < 5


def test_the_memory_backend_needs_nothing_to_be_ready():
    assert build_readiness_checks(environ={"S3_QUERY_BACKEND": "memory"}) == ()


def test_readiness_names_what_is_missing_without_connection_detail(monkeypatch, tmp_path):
    monkeypatch.setattr("ingestion.composition.CATALOGUE_CONNECT_TIMEOUT", 1)
    checks = dict(build_readiness_checks(environ={
        "S3_QUERY_BACKEND": "catalogue", "INGESTION_CATALOGUE_DSN": BLACKHOLE,
        "INGESTION_OBJECT_STORE": str(tmp_path / "absent")}))

    assert checks["catalogue"]() == "the catalogue database could not be reached"
    assert checks["object_store"]() == "the object store is not accessible"
