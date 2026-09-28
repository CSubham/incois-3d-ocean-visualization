"""Deployment-neutral S3 reads consumed by processing and delivery stages.

This module is deliberately independent of storage implementations and
deployment configuration.  Importing it performs no I/O and imports only the
standard library and xarray.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal

import xarray as xr


VerticalPositive = Literal["down", "up"]


def _json_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an immutable copy containing only JSON-compatible values."""
    def freeze(item: Any, path: str) -> Any:
        if isinstance(item, Mapping):
            frozen: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} contains a non-text key")
                frozen[key] = freeze(child, f"{path}.{key}")
            return MappingProxyType(frozen)
        if isinstance(item, (list, tuple)):
            return tuple(freeze(child, f"{path}[]") for child in item)
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float) and isfinite(item):
            return item
        raise ValueError(f"{path} is not JSON-compatible")

    return freeze(dict(value), "provenance")


def _required_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


@dataclass(frozen=True)
class VariableSummary:
    """One variable advertised by a managed dataset version."""

    name: str
    units: str | None

    def __post_init__(self) -> None:
        _required_text(self.name, "variable name")


@dataclass(frozen=True)
class DatasetExtent:
    """Catalogue extents without opening the scientific object."""

    time_start: str | None
    time_end: str | None
    depth_min: float | None
    depth_max: float | None
    west: float | None
    east: float | None
    south: float | None
    north: float | None


@dataclass(frozen=True)
class DatasetVersionSummary:
    """A model version available to downstream catalogue consumers.

    ``id`` is the stable catalogue import id and ``dataset`` is the source's
    stable dataset id.  Level and step values are counts from the stored
    coordinate dimensions, not inferred samples.
    """

    id: str
    dataset: str
    geometry: str
    variables: tuple[VariableSummary, ...]
    depth_levels: int
    time_steps: int
    extent: DatasetExtent
    created_at: str

    def __post_init__(self) -> None:
        _required_text(self.id, "dataset version id")
        _required_text(self.dataset, "dataset id")
        _required_text(self.geometry, "geometry")
        _required_text(self.created_at, "created_at")
        if self.depth_levels < 1 or self.time_steps < 1:
            raise ValueError("model versions require depth and time levels")


@dataclass(frozen=True)
class ModelFieldDescriptor:
    """Semantic identity and references for one decoded scalar model field."""

    dataset_id: str
    dataset_version_id: str
    source_id: str
    variable: str
    units: str
    standard_name: str | None
    time_coordinate: str
    depth_coordinate: str
    latitude_coordinate: str
    longitude_coordinate: str
    crs: str
    vertical_positive: VerticalPositive
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "dataset_id", "dataset_version_id", "source_id", "variable",
            "units", "time_coordinate", "depth_coordinate",
            "latitude_coordinate", "longitude_coordinate", "crs",
        ):
            _required_text(getattr(self, name), name)
        if self.vertical_positive not in ("down", "up"):
            raise ValueError("vertical_positive must be 'down' or 'up'")
        if not isinstance(self.provenance, Mapping):
            raise ValueError("provenance must be a mapping")
        object.__setattr__(self, "provenance",
                           _json_mapping(self.provenance))


class ManagedFieldClosed(RuntimeError):
    """A managed field was accessed outside its resource lifetime."""


class ManagedModelField(AbstractContextManager["ManagedModelField"]):
    """A decoded dataset tied to a deterministic backend lifetime."""

    __slots__ = ("descriptor", "_close", "_closed", "_dataset")

    def __init__(self, dataset: xr.Dataset, descriptor: ModelFieldDescriptor,
                 *, close: Callable[[], None] | None = None) -> None:
        if not isinstance(dataset, xr.Dataset):
            raise TypeError("dataset must be an xarray.Dataset")
        self._dataset = dataset
        self.descriptor = descriptor
        self._close = close if close is not None else dataset.close
        self._closed = False

    @property
    def dataset(self) -> xr.Dataset:
        if self._closed:
            raise ManagedFieldClosed("the managed model field is closed")
        return self._dataset

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._close()
        except Exception:
            raise ModelFieldQueryError(
                "the managed model field could not be closed") from None
        finally:
            self._closed = True

    def __enter__(self) -> "ManagedModelField":
        if self._closed:
            raise ManagedFieldClosed("the managed model field is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            "ManagedModelField("
            f"dataset_version_id={self.descriptor.dataset_version_id!r}, "
            f"variable={self.descriptor.variable!r}, closed={self.closed})"
        )


class ModelFieldQueryError(Exception):
    """Base class for safe failures at the S3 read boundary."""


class VersionNotFound(ModelFieldQueryError):
    def __init__(self, dataset_version_id: str) -> None:
        super().__init__(
            f"dataset version {dataset_version_id!r} does not exist")
        self.dataset_version_id = dataset_version_id


class NotAModelField(ModelFieldQueryError):
    def __init__(self, dataset_version_id: str, geometry: str) -> None:
        super().__init__(
            f"dataset version {dataset_version_id!r} has {geometry!r} "
            "geometry, not model-grid geometry")
        self.dataset_version_id = dataset_version_id
        self.geometry = geometry


class VariableUnavailable(ModelFieldQueryError):
    def __init__(self, dataset_version_id: str, variable: str) -> None:
        super().__init__(
            f"variable {variable!r} is unavailable in dataset version "
            f"{dataset_version_id!r}")
        self.dataset_version_id = dataset_version_id
        self.variable = variable


class UndeclaredReference(ModelFieldQueryError):
    def __init__(self, dataset_version_id: str, reference: str) -> None:
        super().__init__(
            f"dataset version {dataset_version_id!r} does not declare "
            f"{reference}")
        self.dataset_version_id = dataset_version_id
        self.reference = reference


class ModelFieldQuery(ABC):
    """Read-only S3 boundary for model catalogue and scalar fields."""

    @abstractmethod
    def list_model_versions(self) -> tuple[DatasetVersionSummary, ...]:
        """List managed model-grid versions without opening their arrays."""

    @abstractmethod
    def describe_version(
            self, dataset_version_id: str) -> DatasetVersionSummary:
        """Describe one model-grid version by its stable catalogue id."""

    @abstractmethod
    def open_model_field(
            self, dataset_version_id: str,
            variable: str) -> ManagedModelField:
        """Open one complete decoded scalar variable without processing it."""


__all__ = [
    "DatasetExtent", "DatasetVersionSummary", "ManagedFieldClosed",
    "ManagedModelField", "ModelFieldDescriptor", "ModelFieldQuery",
    "ModelFieldQueryError", "NotAModelField", "UndeclaredReference",
    "VariableSummary", "VariableUnavailable", "VersionNotFound",
    "VerticalPositive",
]
