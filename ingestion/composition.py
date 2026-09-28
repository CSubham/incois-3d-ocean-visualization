"""Composition root for replaceable S3 model-field query implementations."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from ingestion.config import (
    CATALOGUE_DSN, MODEL_SOURCE_REFERENCES, OBJECT_STORE_ROOT,
    S3_QUERY_BACKEND,
)
from ingestion.query import ModelFieldQuery
from ingestion.query_memory import (
    InMemoryDatasetVersion, InMemoryModelFieldQuery,
)
from ingestion.storage.objects import LocalObjectStore
from ingestion.storage.query import CatalogueModelFieldQuery


def build_model_field_query(
    *,
    environ: Mapping[str, str] | None = None,
    memory_versions: Iterable[InMemoryDatasetVersion] = (),
) -> ModelFieldQuery:
    """Build the configured query once; workflows receive only its contract."""
    configured = os.environ if environ is None else environ
    backend = configured.get("S3_QUERY_BACKEND", S3_QUERY_BACKEND).strip().lower()
    if backend == "memory":
        return InMemoryModelFieldQuery(memory_versions)
    if backend == "catalogue":
        dsn = configured.get("INGESTION_CATALOGUE_DSN", CATALOGUE_DSN)
        object_root = Path(configured.get(
            "INGESTION_OBJECT_STORE", str(OBJECT_STORE_ROOT)))
        return CatalogueModelFieldQuery(
            dsn,
            LocalObjectStore(object_root),
            MODEL_SOURCE_REFERENCES,
        )
    raise ValueError(
        "S3_QUERY_BACKEND must be 'catalogue' or 'memory', "
        f"not {backend!r}")


__all__ = ["build_model_field_query"]
