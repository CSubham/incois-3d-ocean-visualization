"""Composition root for replaceable S3 scientific query implementations."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
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
from ingestion.storage.objects import LocalObjectStore
from ingestion.storage.query import CatalogueModelFieldQuery


def build_model_field_query(
    *,
    environ: Mapping[str, str] | None = None,
    memory_versions: Iterable[InMemoryDatasetVersion] = (),
) -> ScientificQuery:
    """Build the configured query once; workflows receive only its contract."""
    configured = os.environ if environ is None else environ
    backend = configured.get("S3_QUERY_BACKEND", S3_QUERY_BACKEND).strip().lower()
    if backend == "memory":
        return InMemoryModelFieldQuery(memory_versions)
    if backend == "catalogue":
        dsn = configured.get("INGESTION_CATALOGUE_DSN") or CATALOGUE_DSN
        if not dsn:
            raise ConfigurationError(
                "INGESTION_CATALOGUE_DSN is not set; the catalogue query "
                "backend cannot start without it")
        object_root = Path(configured.get(
            "INGESTION_OBJECT_STORE", str(OBJECT_STORE_ROOT)))
        return CatalogueModelFieldQuery(
            dsn,
            LocalObjectStore(object_root),
            SOURCE_REFERENCES,
            connect_timeout=CATALOGUE_CONNECT_TIMEOUT,
        )
    raise ValueError(
        "S3_QUERY_BACKEND must be 'catalogue' or 'memory', "
        f"not {backend!r}")


__all__ = ["build_model_field_query"]
