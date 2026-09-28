"""Implementations of the storage port.

`PostgresStorage` is the real one: arrays to an object store, catalogue and
observation positions to PostgreSQL with PostGIS.

The sinks remain for tests and for running without a database.
"""

from ingestion.storage.objects import (
    LocalObjectStore, ObjectStore, ObjectStoreError,
)
from ingestion.storage.postgres import PostgresStorage, StorageError
from ingestion.storage.query import CatalogueModelFieldQuery
from ingestion.storage.sink import DevelopmentSink, RecordingSink

__all__ = ["PostgresStorage", "StorageError", "ObjectStore",
           "LocalObjectStore", "ObjectStoreError", "DevelopmentSink",
           "RecordingSink", "CatalogueModelFieldQuery"]
