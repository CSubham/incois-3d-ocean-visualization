"""Public in-memory implementation of the S3 scientific read contract."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

import numpy as np
import xarray as xr

from ingestion.query import (
    DatasetVersionListing, DatasetVersionSummary, ManagedModelField,
    ModelFieldDescriptor, ModelFieldQueryError, NotAModelField,
    NotAnObservationProfile,
    ObservationProfile, ProfileIdentity, ProfileMarker, ProfileNotFound,
    ProfileSearch, ProfileValue, ProfileVariable, ScientificQuery,
    UnavailableDatasetVersion, UndeclaredReference, VariableUnavailable,
    VersionNotFound,
)


_OBSERVATION_GEOMETRIES = {"profile", "trajectory", "trajectory_profile",
                           "point"}
_PLATFORM_HINTS = ("platform_number", "platform", "wmo", "float",
                   "trajectory", "glider", "station")
_CYCLE_HINTS = ("cycle_number", "cycle", "profile_id", "profile", "cast")


@dataclass(frozen=True)
class InMemoryDatasetVersion:
    """One immutable registration for tests and local composition."""

    summary: DatasetVersionSummary
    dataset: xr.Dataset
    descriptors: Mapping[str, ModelFieldDescriptor]
    undeclared_references: Mapping[str, str] = field(default_factory=dict)
    coordinate_names: Mapping[str, str] = field(default_factory=dict)
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "descriptors", MappingProxyType(dict(self.descriptors)))
        object.__setattr__(
            self, "undeclared_references",
            MappingProxyType(dict(self.undeclared_references)),
        )
        object.__setattr__(
            self, "coordinate_names",
            MappingProxyType(dict(self.coordinate_names)),
        )


class InMemoryModelFieldQuery(ScientificQuery):
    """A replaceable query fake with the same semantics as the catalogue."""

    def __init__(self,
                 versions: Iterable[InMemoryDatasetVersion] = ()) -> None:
        supplied = tuple(versions)
        registered = {item.summary.id: item for item in supplied}
        if len(registered) != len(supplied):
            raise ValueError("dataset version ids must be unique")
        self._versions = MappingProxyType(registered)

    def list_model_versions(self) -> DatasetVersionListing:
        summaries = [
            item.summary for item in self._versions.values()
            if item.summary.geometry == "grid"
            and item.unavailable_reason is None
        ]
        unavailable = tuple(
            UnavailableDatasetVersion(item.summary.id, item.unavailable_reason)
            for item in self._versions.values()
            if item.summary.geometry == "grid"
            and item.unavailable_reason is not None
        )
        return DatasetVersionListing(
            versions=tuple(sorted(
                summaries, key=lambda item: (item.created_at, item.id),
                reverse=True,
            )),
            unavailable=unavailable,
        )

    def describe_version(
            self, dataset_version_id: str) -> DatasetVersionSummary:
        version = self._version(dataset_version_id)
        self._require_grid(version.summary)
        return version.summary

    def open_model_field(
            self, dataset_version_id: str,
            variable: str) -> ManagedModelField:
        version = self._version(dataset_version_id)
        self._require_grid(version.summary)
        if variable in version.undeclared_references:
            raise UndeclaredReference(
                dataset_version_id,
                version.undeclared_references[variable],
            )
        descriptor = version.descriptors.get(variable)
        declared = {item.name for item in version.summary.variables}
        if (descriptor is None or variable not in declared
                or variable not in version.dataset.data_vars):
            raise VariableUnavailable(dataset_version_id, variable)
        dataset = version.dataset[[variable]].copy(deep=False)
        return ManagedModelField(dataset, descriptor)

    def find_profile_markers(
            self, search: ProfileSearch) -> tuple[ProfileMarker, ...]:
        start = _parse_time(search.time_start)
        end = _parse_time(search.time_end)
        if start > end:
            raise ValueError("profile search times must be ordered")
        markers: list[ProfileMarker] = []
        for version in self._versions.values():
            if version.summary.geometry not in _OBSERVATION_GEOMETRIES:
                continue
            for identity, positions in _profile_groups(version):
                marker = _profile_marker(version, identity, positions)
                observed_at = _parse_time(marker.observed_at)
                if (search.west <= marker.longitude <= search.east
                        and search.south <= marker.latitude <= search.north
                        and start <= observed_at <= end):
                    markers.append(marker)
        return tuple(sorted(
            markers,
            key=lambda item: (
                item.observed_at, item.identity.dataset_version_id,
                item.identity.platform_id, item.identity.cycle,
            ),
        ))

    def get_profile(self, identity: ProfileIdentity) -> ObservationProfile:
        version = self._version(identity.dataset_version_id)
        if version.summary.geometry not in _OBSERVATION_GEOMETRIES:
            raise NotAnObservationProfile(
                identity.dataset_version_id, version.summary.geometry)
        for candidate, positions in _profile_groups(version):
            if candidate == identity:
                return _observation_profile(version, identity, positions)
        raise ProfileNotFound(identity)

    def _version(self, dataset_version_id: str) -> InMemoryDatasetVersion:
        try:
            version = self._versions[dataset_version_id]
        except KeyError:
            raise VersionNotFound(dataset_version_id) from None
        if version.unavailable_reason is not None:
            raise ModelFieldQueryError(version.unavailable_reason)
        return version

    @staticmethod
    def _require_grid(summary: DatasetVersionSummary) -> None:
        if summary.geometry != "grid":
            raise NotAModelField(summary.id, summary.geometry)


def _profile_groups(version: InMemoryDatasetVersion
                    ) -> tuple[tuple[ProfileIdentity, np.ndarray], ...]:
    dataset = version.dataset
    platform_name = _named(dataset, _PLATFORM_HINTS)
    cycle_name = _named(dataset, _CYCLE_HINTS)
    if platform_name is None or cycle_name is None:
        return ()
    platform = dataset[platform_name]
    cycle = dataset[cycle_name]
    if len(platform.dims) != 1 or cycle.dims != platform.dims:
        raise UndeclaredReference(
            version.summary.id, "one-dimensional platform and cycle identity")
    grouped: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    for index, (platform_id, cycle_id) in enumerate(zip(
            _text_values(platform.values), _text_values(cycle.values))):
        if platform_id and cycle_id:
            grouped[(platform_id, cycle_id)].append(index)
    return tuple(
        (ProfileIdentity(version.summary.id, platform_id, cycle_id),
         np.asarray(indices, dtype=np.intp))
        for (platform_id, cycle_id), indices in grouped.items()
    )


def _profile_marker(
    version: InMemoryDatasetVersion,
    identity: ProfileIdentity,
    positions: np.ndarray,
) -> ProfileMarker:
    names = _profile_coordinate_names(version)
    dataset = version.dataset
    sample_dim = _sample_dimension(dataset, names["time"], version.summary.id)
    selected = dataset.isel({sample_dim: positions})
    times = tuple(_timestamp(value)
                  for value in np.ravel(selected[names["time"]].values))
    present_times = tuple(value for value in times if value is not None)
    if not present_times:
        raise UndeclaredReference(version.summary.id, "profile timestamps")
    latitude = float(np.mean(selected[names["latitude"]].values))
    longitude = _signed(float(np.mean(selected[names["longitude"]].values)))
    return ProfileMarker(
        identity=identity,
        longitude=longitude,
        latitude=latitude,
        observed_at=min(present_times),
    )


def _observation_profile(
    version: InMemoryDatasetVersion,
    identity: ProfileIdentity,
    positions: np.ndarray,
) -> ObservationProfile:
    names = _profile_coordinate_names(version)
    dataset = version.dataset
    sample_dim = _sample_dimension(dataset, names["vertical"], version.summary.id)
    selected = dataset.isel({sample_dim: positions})
    variables = tuple(
        _profile_variable(selected, item.name, item.units,
                          version.summary.id, sample_dim)
        for item in version.summary.variables
    )
    return ObservationProfile(
        identity=identity,
        depth_coordinate=names["vertical"],
        depth_units=_optional_text(
            selected[names["vertical"]].attrs.get("units")),
        depth_values=_profile_values(
            selected[names["vertical"]], sample_dim, version.summary.id),
        time_coordinate=names["time"],
        timestamps=tuple(
            _timestamp(value)
            for value in np.ravel(selected[names["time"]].values)
        ),
        variables=variables,
    )


def _profile_variable(dataset: xr.Dataset, name: str, units: str | None,
                      version_id: str, sample_dim: str) -> ProfileVariable:
    if name not in dataset.variables:
        raise VariableUnavailable(version_id, name)
    quality_name = _quality_name(dataset, name)
    quality = dataset[quality_name] if quality_name is not None else None
    return ProfileVariable(
        name=name,
        units=units,
        values=_profile_values(dataset[name], sample_dim, version_id),
        quality_control_name=quality_name,
        quality_control=(
            _profile_values(quality, sample_dim, version_id)
            if quality is not None else None
        ),
        qc_flag_values=(
            _qc_flag_values(quality, version_id)
            if quality is not None else None
        ),
        qc_flag_meanings=(
            _optional_qc_text(quality, "flag_meanings", version_id)
            if quality is not None else None
        ),
        qc_conventions=(
            _optional_qc_text(quality, "conventions", version_id)
            if quality is not None else None
        ),
    )


def _profile_values(array: xr.DataArray, sample_dim: str,
                    version_id: str) -> tuple[ProfileValue, ...]:
    if array.dims != (sample_dim,):
        raise UndeclaredReference(
            version_id, f"one-dimensional profile variable {array.name!r}")
    return tuple(_profile_value(value) for value in np.ravel(array.values))


def _profile_value(value: Any) -> ProfileValue:
    if np.ma.is_masked(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and np.isnan(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _profile_coordinate_names(version: InMemoryDatasetVersion
                              ) -> Mapping[str, str]:
    names = version.coordinate_names
    for role in ("time", "vertical", "latitude", "longitude"):
        name = names.get(role)
        if not isinstance(name, str) or name not in version.dataset.variables:
            exposed = "depth" if role == "vertical" else role
            raise UndeclaredReference(
                version.summary.id, f"the {exposed} coordinate name")
    return names


def _sample_dimension(dataset: xr.Dataset, coordinate: str,
                      version_id: str) -> str:
    dims = dataset[coordinate].dims
    if len(dims) != 1:
        raise UndeclaredReference(
            version_id, f"one-dimensional coordinate {coordinate!r}")
    return dims[0]


def _named(dataset: xr.Dataset, hints: tuple[str, ...]) -> str | None:
    lowered = {str(name).lower(): str(name) for name in dataset.variables}
    for hint in hints:
        if hint in lowered:
            return lowered[hint]
    for name in dataset.variables:
        if any(hint in str(name).lower() for hint in hints):
            return str(name)
    return None


def _quality_name(dataset: xr.Dataset, variable: str) -> str | None:
    expected = f"{variable}_qc".lower()
    return next(
        (str(name) for name in dataset.variables
         if str(name).lower() == expected),
        None,
    )


def _qc_flag_values(array: xr.DataArray,
                    version_id: str) -> tuple[ProfileValue, ...] | None:
    if "flag_values" not in array.attrs:
        return None
    values = np.asarray(array.attrs["flag_values"], dtype=object)
    if values.ndim > 1:
        raise UndeclaredReference(
            version_id,
            f"scalar or vector QC flag_values on {array.name!r}",
        )
    return tuple(
        _qc_attribute_scalar(value, array.name, "flag_values", version_id)
        for value in values.reshape(-1)
    )


def _optional_qc_text(array: xr.DataArray, attribute: str,
                      version_id: str) -> str | None:
    if attribute not in array.attrs:
        return None
    value = _qc_attribute_scalar(
        array.attrs[attribute], array.name, attribute, version_id)
    if not isinstance(value, str):
        raise UndeclaredReference(
            version_id, f"text QC {attribute} on {array.name!r}")
    return value


def _qc_attribute_scalar(value: Any, variable: Any, attribute: str,
                         version_id: str) -> ProfileValue:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise UndeclaredReference(
                version_id, f"UTF-8 QC {attribute} on {variable!r}") from None
    if (not isinstance(value, (str, int, float, bool))
            or isinstance(value, float) and not np.isfinite(value)):
        raise UndeclaredReference(
            version_id,
            f"scalar text or numeric QC {attribute} on {variable!r}",
        )
    return value


def _text_values(values: Any) -> tuple[str, ...]:
    return tuple(str(_profile_value(value) or "")
                 for value in np.ravel(values))


def _timestamp(value: Any) -> str | None:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return str(np.datetime_as_string(value, unit="ns"))
    if isinstance(value, datetime):
        return value.isoformat()
    plain = _profile_value(value)
    return str(plain) if plain is not None else None


def _parse_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _signed(longitude: float) -> float:
    return longitude - 360.0 if longitude > 180.0 else longitude


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None else None


__all__ = ["InMemoryDatasetVersion", "InMemoryModelFieldQuery"]
