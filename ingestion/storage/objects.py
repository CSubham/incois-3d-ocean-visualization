"""The scientific object store.

Arrays are written once and never edited. A version is identified by the
import that produced it, so the same selection imported twice produces two
versions rather than one overwritten one -- which is what makes a stored
reference safe to hand downstream.

The interface is deliberately small. Local files serve development; an
object-storage backend replaces this class and nothing else.
"""

from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import xarray as xr

from ingestion.domain.errors import IngestionError


class ObjectStoreError(IngestionError):
    """An array could not be written or read back."""


class ObjectStore(ABC):
    """Where scientific arrays live."""

    @abstractmethod
    def put(self, import_id: str, dataset: xr.Dataset) -> str:
        """Store a dataset and return a stable reference to it."""

    @abstractmethod
    def open(self, reference: str) -> xr.Dataset:
        """Read back what a reference points at."""

    @abstractmethod
    def exists(self, reference: str) -> bool:
        """Whether a reference still resolves."""


class LocalObjectStore(ObjectStore):
    """Immutable NetCDF files under a root directory.

    Writes go to a temporary file and are moved into place, so a reference
    never points at a half-written array: either the move happened or it did
    not.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, reference: str) -> Path:
        candidate = (self.root / reference).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ObjectStoreError(f"{reference!r} lies outside the store")
        return candidate

    def put(self, import_id: str, dataset: xr.Dataset) -> str:
        reference = f"{import_id}.nc"
        destination = self._path(reference)
        if destination.exists():
            raise ObjectStoreError(
                f"{reference} already exists. Stored arrays are immutable; a "
                "repeat import is a new version, not an overwrite.")

        partial: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=f".{destination.name}.",
                    suffix=".part", delete=False) as handle:
                partial = Path(handle.name)
            dataset.to_netcdf(partial)
            os.replace(partial, destination)
            return reference
        except Exception as exc:
            if partial is not None:
                partial.unlink(missing_ok=True)
            raise ObjectStoreError(
                f"could not store the array: {exc}") from exc

    def open(self, reference: str) -> xr.Dataset:
        path = self._path(reference)
        if not path.exists():
            raise ObjectStoreError(f"{reference} is not in the store")
        try:
            return xr.open_dataset(path)
        except Exception as exc:
            raise ObjectStoreError(
                f"{reference} could not be read back: {exc}") from exc

    def exists(self, reference: str) -> bool:
        try:
            return self._path(reference).exists()
        except ObjectStoreError:
            return False
