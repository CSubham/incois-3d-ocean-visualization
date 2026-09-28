"""Deployment-neutral S3 reads consumed by processing and delivery stages.

This module is deliberately independent of storage implementations and
deployment configuration.  Importing it performs no I/O and imports only the
standard library and xarray.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from types import MappingProxyType
from typing import Any, Literal, TypeAlias, overload

import xarray as xr


VerticalPositive = Literal["down", "up"]
ProfileValue: TypeAlias = str | bool | int | float | None


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


def _iso_datetime(value: str, name: str) -> datetime:
    _required_text(value, name)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError(f"{name} must be an ISO timestamp") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    depth_values: tuple[float, ...]
    time_values: tuple[str, ...]
    extent: DatasetExtent
    created_at: str

    def __post_init__(self) -> None:
        _required_text(self.id, "dataset version id")
        _required_text(self.dataset, "dataset id")
        _required_text(self.geometry, "geometry")
        _required_text(self.created_at, "created_at")
        if self.depth_levels < 1 or self.time_steps < 1:
            raise ValueError("dataset versions require depth and time levels")
        if len(self.depth_values) != self.depth_levels:
            raise ValueError("depth_values must match depth_levels")
        if len(self.time_values) != self.time_steps:
            raise ValueError("time_values must match time_steps")
        if not all(isfinite(value) for value in self.depth_values):
            raise ValueError("depth_values must be finite")
        for value in self.time_values:
            _required_text(value, "time value")


@dataclass(frozen=True)
class UnavailableDatasetVersion:
    """A catalogue version omitted because its managed object is unreadable."""

    id: str
    reason: str

    def __post_init__(self) -> None:
        _required_text(self.id, "dataset version id")
        _required_text(self.reason, "unavailable reason")


@dataclass(frozen=True)
class DatasetVersionListing(Sequence[DatasetVersionSummary]):
    """Readable versions plus explicit, safe reports for omitted versions."""

    versions: tuple[DatasetVersionSummary, ...]
    unavailable: tuple[UnavailableDatasetVersion, ...] = ()

    @overload
    def __getitem__(self, index: int) -> DatasetVersionSummary: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[DatasetVersionSummary, ...]: ...

    def __getitem__(self, index: int | slice
                    ) -> DatasetVersionSummary | tuple[DatasetVersionSummary, ...]:
        return self.versions[index]

    def __iter__(self) -> Iterator[DatasetVersionSummary]:
        return iter(self.versions)

    def __len__(self) -> int:
        return len(self.versions)


@dataclass(frozen=True)
class ProfileSearch:
    """Inclusive spatial and temporal bounds for observation markers."""

    west: float
    east: float
    south: float
    north: float
    time_start: str
    time_end: str

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (
                self.west, self.east, self.south, self.north)):
            raise ValueError("profile search bounds must be finite")
        if not (-180.0 <= self.west <= self.east <= 180.0):
            raise ValueError("profile longitude bounds must be ordered")
        if not (-90.0 <= self.south <= self.north <= 90.0):
            raise ValueError("profile latitude bounds must be ordered")
        start = _iso_datetime(
            self.time_start, "profile search time_start")
        end = _iso_datetime(self.time_end, "profile search time_end")
        if start > end:
            raise ValueError("profile search times must be ordered")


@dataclass(frozen=True)
class ProfileIdentity:
    """Stable identity of one profile inside one immutable dataset version."""

    dataset_version_id: str
    platform_id: str
    cycle: str

    def __post_init__(self) -> None:
        _required_text(self.dataset_version_id, "dataset version id")
        _required_text(self.platform_id, "platform id")
        _required_text(self.cycle, "cycle")


@dataclass(frozen=True)
class ProfileMarker:
    """Geospatially exact marker for one retrievable observation profile."""

    identity: ProfileIdentity
    longitude: float
    latitude: float
    observed_at: str

    def __post_init__(self) -> None:
        if not isfinite(self.longitude) or not -180.0 <= self.longitude <= 180.0:
            raise ValueError("profile longitude must be signed degrees")
        if not isfinite(self.latitude) or not -90.0 <= self.latitude <= 90.0:
            raise ValueError("profile latitude must be degrees north")
        _required_text(self.observed_at, "profile observed_at")


@dataclass(frozen=True)
class ProfileVariable:
    """One exact measured series and its source quality-control values."""

    name: str
    units: str | None
    values: tuple[ProfileValue, ...]
    quality_control_name: str | None = None
    quality_control: tuple[ProfileValue, ...] | None = None
    qc_flag_values: tuple[ProfileValue, ...] | None = None
    qc_flag_meanings: str | None = None
    qc_conventions: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.name, "profile variable name")
        if self.quality_control_name is None and self.quality_control is not None:
            raise ValueError("quality-control values require their variable name")
        qc_metadata = (
            self.qc_flag_values, self.qc_flag_meanings, self.qc_conventions)
        if (self.quality_control_name is None
                and any(value is not None for value in qc_metadata)):
            raise ValueError(
                "quality-control metadata requires its variable name")
        if self.quality_control_name is not None:
            _required_text(self.quality_control_name, "quality-control name")
            if self.quality_control is None:
                raise ValueError("quality-control name requires values")
        if (self.quality_control is not None
                and len(self.quality_control) != len(self.values)):
            raise ValueError("quality-control values must match measurements")
        if self.qc_flag_values is not None:
            object.__setattr__(self, "qc_flag_values",
                               tuple(self.qc_flag_values))
        if self.qc_flag_meanings is not None:
            _required_text(self.qc_flag_meanings, "QC flag meanings")
        if self.qc_conventions is not None:
            _required_text(self.qc_conventions, "QC conventions")


@dataclass(frozen=True)
class ObservationProfile:
    """Exact depth-versus-variable observations for one selected profile."""

    identity: ProfileIdentity
    depth_coordinate: str
    depth_units: str | None
    depth_values: tuple[ProfileValue, ...]
    time_coordinate: str
    timestamps: tuple[str | None, ...]
    variables: tuple[ProfileVariable, ...]

    def __post_init__(self) -> None:
        _required_text(self.depth_coordinate, "profile depth coordinate")
        _required_text(self.time_coordinate, "profile time coordinate")
        measurements = len(self.depth_values)
        if measurements < 1:
            raise ValueError("profiles require at least one measurement")
        if len(self.timestamps) != measurements:
            raise ValueError("profile timestamps must match depth values")
        if not self.variables:
            raise ValueError("profiles require at least one measured variable")
        if any(len(variable.values) != measurements
               for variable in self.variables):
            raise ValueError("profile variable values must match depth values")


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


class ProfileNotFound(ModelFieldQueryError):
    def __init__(self, identity: ProfileIdentity) -> None:
        super().__init__(
            "the requested observation profile does not exist in dataset "
            f"version {identity.dataset_version_id!r}")
        self.identity = identity


class NotAnObservationProfile(ModelFieldQueryError):
    def __init__(self, dataset_version_id: str, geometry: str) -> None:
        super().__init__(
            f"dataset version {dataset_version_id!r} has {geometry!r} "
            "geometry, not observation-profile geometry")
        self.dataset_version_id = dataset_version_id
        self.geometry = geometry


class ModelFieldQuery(ABC):
    """Read-only S3 boundary for model catalogue and scalar fields."""

    @abstractmethod
    def list_model_versions(self) -> DatasetVersionListing:
        """List readable grids and report versions that could not be read."""

    @abstractmethod
    def describe_version(
            self, dataset_version_id: str) -> DatasetVersionSummary:
        """Describe one model-grid version by its stable catalogue id."""

    @abstractmethod
    def open_model_field(
            self, dataset_version_id: str,
            variable: str) -> ManagedModelField:
        """Open one complete decoded scalar variable without processing it."""


class ObservationQuery(ABC):
    """Read-only S3 boundary for observation markers and exact profiles."""

    @abstractmethod
    def find_profile_markers(
            self, search: ProfileSearch) -> tuple[ProfileMarker, ...]:
        """Find exactly identifiable profiles inside inclusive bounds."""

    @abstractmethod
    def get_profile(self, identity: ProfileIdentity) -> ObservationProfile:
        """Retrieve one exact depth-versus-variable observation profile."""


class ScientificQuery(ModelFieldQuery, ObservationQuery, ABC):
    """Complete deployment-neutral S3 read boundary."""


__all__ = [
    "DatasetExtent", "DatasetVersionListing", "DatasetVersionSummary",
    "ManagedFieldClosed", "ManagedModelField", "ModelFieldDescriptor",
    "ModelFieldQuery", "ModelFieldQueryError", "NotAModelField",
    "NotAnObservationProfile", "ObservationProfile", "ObservationQuery",
    "ProfileIdentity", "ProfileMarker", "ProfileNotFound", "ProfileSearch",
    "ProfileValue", "ProfileVariable", "ScientificQuery",
    "UnavailableDatasetVersion", "UndeclaredReference", "VariableSummary",
    "VariableUnavailable", "VersionNotFound", "VerticalPositive",
]
