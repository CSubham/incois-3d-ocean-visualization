"""Composition root for replaceable S3 scientific query implementations."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from ingestion.config import (
    CATALOGUE_CONNECT_TIMEOUT, CATALOGUE_DSN, OBJECT_STORE_ROOT,
    SOURCE_REFERENCES, S3_QUERY_BACKEND,
)
from ingestion.domain.errors import ConfigurationError
from ingestion.query import ScientificQuery
from ingestion.query_memory import (
    InMemoryDatasetVersion, InMemoryModelFieldQuery,
)
from ingestion.storage.migrate import MigrationError, schema_status
from ingestion.storage.objects import LocalObjectStore
from ingestion.storage.query import CatalogueModelFieldQuery


#: A named readiness probe: returns None when ready, else why not.
ReadinessCheck = tuple[str, Callable[[], str | None]]


def _backend(configured: Mapping[str, str]) -> str:
    return configured.get("S3_QUERY_BACKEND", S3_QUERY_BACKEND).strip().lower()


def _catalogue_dsn(configured: Mapping[str, str]) -> str:
    dsn = configured.get("INGESTION_CATALOGUE_DSN") or CATALOGUE_DSN
    if not dsn:
        raise ConfigurationError(
            "INGESTION_CATALOGUE_DSN is not set; the catalogue query "
            "backend cannot start without it")
    return dsn


def _object_root(configured: Mapping[str, str]) -> Path:
    return Path(configured.get("INGESTION_OBJECT_STORE", str(OBJECT_STORE_ROOT)))


def build_model_field_query(
    *,
    environ: Mapping[str, str] | None = None,
    memory_versions: Iterable[InMemoryDatasetVersion] = (),
) -> ScientificQuery:
    """Build the configured query once; workflows receive only its contract."""
    configured = os.environ if environ is None else environ
    backend = _backend(configured)
    if backend == "memory":
        return InMemoryModelFieldQuery(memory_versions)
    if backend == "catalogue":
        return CatalogueModelFieldQuery(
            _catalogue_dsn(configured),
            LocalObjectStore(_object_root(configured)),
            SOURCE_REFERENCES,
            connect_timeout=CATALOGUE_CONNECT_TIMEOUT,
        )
    raise ValueError(
        "S3_QUERY_BACKEND must be 'catalogue' or 'memory', "
        f"not {backend!r}")


def build_readiness_checks(
    *, environ: Mapping[str, str] | None = None,
) -> tuple[ReadinessCheck, ...]:
    """What must answer before the configured query can serve a request.

    The in-memory backend depends on nothing. The catalogue backend needs
    its database reachable at exactly this code's schema version, and its
    object store present. Reasons never carry connection details.
    """
    configured = os.environ if environ is None else environ
    if _backend(configured) != "catalogue":
        return ()
    dsn = _catalogue_dsn(configured)
    object_root = _object_root(configured)

    def catalogue() -> str | None:
        try:
            return schema_status(
                dsn, connect_timeout=CATALOGUE_CONNECT_TIMEOUT).reason
        except MigrationError as exc:
            return str(exc)
        except Exception:
            return "the catalogue database could not be reached"

    def object_store() -> str | None:
        return None if object_root.is_dir() else "the object store is not accessible"

    return (("catalogue", catalogue), ("object_store", object_store))


__all__ = ["build_model_field_query", "build_readiness_checks"]
