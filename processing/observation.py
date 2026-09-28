"""Pure observation marker and exact-profile scientific products."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import xarray as xr

from processing.domain import (
    CoordinateTransform, DatasetIdentity, MaskSemantics, SpatialReference,
    _frozen_mapping, _readonly_array,
)
from processing.errors import (
    AllMissingObservationError, InvalidRequestError, ObservationIdentityError,
    ObservationValidationError, ObservationVariableError,
)


MARKER_SCHEMA_VERSION = "s4.observation-markers/1.0"
PROFILE_SCHEMA_VERSION = "s4.observation-profile/1.0"
MARKER_PRODUCT_TYPE = "observation_markers"
PROFILE_PRODUCT_TYPE = "observation_profile"
VERTICAL_KINDS = ("depth", "pressure")

OBSERVATION_IDENTITY_TRANSFORM = CoordinateTransform(
    kind="identity",
    horizontal="source longitude and latitude in the declared CRS; not "
               "averaged, reprojected or re-wrapped",
    vertical="source vertical values in source units and declared positive "
             "direction; not converted, sorted or interpolated",
)

OBSERVATION_MISSING_MASK = MaskSemantics(
    true_means="the source observation has no decoded value",
    sources=("NaN or NaT after decoding", "masked array element"),
    masked_values="not scientific values; consumers must apply the mask",
)


@dataclass(frozen=True)
class ObservationCoordinateRoles:
    platform: str
    cycle: str
    longitude: str
    latitude: str
    time: str
    vertical: str

    def __post_init__(self) -> None:
        names = tuple(getattr(self, name) for name in (
            "platform", "cycle", "longitude", "latitude", "time", "vertical"))
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise InvalidRequestError(
                "platform, cycle, longitude, latitude, time and vertical "
                "coordinate names are required")
        if len(set(names)) != len(names):
            raise InvalidRequestError(
                "observation coordinate roles must use distinct names")


@dataclass(frozen=True)
class ObservationVertical:
    """Meaning of the source vertical coordinate; values are never converted."""

    kind: str
    positive: str

    def __post_init__(self) -> None:
        if self.kind not in VERTICAL_KINDS:
            raise InvalidRequestError(
                f"vertical kind must be one of {VERTICAL_KINDS}, not "
                f"{self.kind!r}")
        if self.positive not in ("down", "up"):
            raise InvalidRequestError(
                "vertical positive direction must be 'down' or 'up'")


@dataclass(frozen=True)
class ObservationDatasetDescriptor:
    """Explicit semantics supplied with a decoded row-oriented dataset."""

    identity: DatasetIdentity
    sample_dimension: str
    coordinates: ObservationCoordinateRoles
    vertical: ObservationVertical
    crs: str
    qc_variables: Mapping[str, str]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.sample_dimension, str) or not self.sample_dimension:
            raise InvalidRequestError("an observation sample_dimension is required")
        if not isinstance(self.crs, str) or not self.crs.strip():
            raise InvalidRequestError("an observation CRS is required")
        if not isinstance(self.qc_variables, Mapping):
            raise InvalidRequestError("qc_variables must map measurements to flags")
        qc_variables = {str(variable): str(flag)
                        for variable, flag in self.qc_variables.items()}
        if any(not variable or not flag
               for variable, flag in qc_variables.items()):
            raise InvalidRequestError(
                "qc_variables cannot contain empty variable or flag names")
        if not isinstance(self.provenance, Mapping):
            raise InvalidRequestError("provenance must be a mapping")
        object.__setattr__(self, "qc_variables",
                           _frozen_mapping(qc_variables))
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))
        recorded = self.provenance.get("import_id")
        if recorded is not None and recorded != self.identity.dataset_version_id:
            raise InvalidRequestError(
                f"provenance import_id {recorded!r} contradicts "
                f"dataset_version_id {self.identity.dataset_version_id!r}")


@dataclass(frozen=True)
class ObservationProfileIdentity:
    platform_id: str
    cycle: str

    def __post_init__(self) -> None:
        if (not isinstance(self.platform_id, str) or not self.platform_id.strip()
                or not isinstance(self.cycle, str) or not self.cycle.strip()):
            raise InvalidRequestError(
                "an exact platform_id and cycle/profile identity are required")


@dataclass(frozen=True)
class ObservationProfileSelection:
    identity: ObservationProfileIdentity
    variables: tuple[str, ...]

    def __post_init__(self) -> None:
        if (not self.variables
                or any(not isinstance(name, str) or not name.strip()
                       for name in self.variables)):
            raise InvalidRequestError(
                "at least one observation variable name is required")
        if len(set(self.variables)) != len(self.variables):
            raise InvalidRequestError(
                "requested observation variable names must be unique")


@dataclass(frozen=True)
class ObservationCoordinateMetadata:
    names: ObservationCoordinateRoles
    sample_dimension: str
    units: Mapping[str, str | None]
    dtypes: Mapping[str, str]
    time_encoding: Mapping[str, str | None]
    vertical_kind: str

    def __post_init__(self) -> None:
        for name in ("units", "dtypes", "time_encoding"):
            object.__setattr__(self, name, _frozen_mapping(getattr(self, name)))


@dataclass(frozen=True)
class ObservationVerticalRange:
    minimum: int | float
    maximum: int | float
    valid_observation_count: int
    missing_observation_count: int


@dataclass(frozen=True)
class ObservationMarker:
    identity: ObservationProfileIdentity
    longitude: Any
    latitude: Any
    time_value: Any
    vertical_range: ObservationVerticalRange
    representative_source_index: int
    source_indices: tuple[int, ...]


@dataclass(frozen=True)
class MarkerGroupingMetadata:
    grouping_keys: tuple[str, str]
    representative_policy: str
    original_observation_count: int
    delivered_marker_count: int


@dataclass(frozen=True)
class ObservationMarkerProduct:
    dataset_identity: DatasetIdentity
    coordinates: ObservationCoordinateMetadata
    spatial_reference: SpatialReference
    provenance: Mapping[str, Any]
    grouping: MarkerGroupingMetadata
    markers: tuple[ObservationMarker, ...]
    coordinate_transform: CoordinateTransform = OBSERVATION_IDENTITY_TRANSFORM
    mask_semantics: MaskSemantics = OBSERVATION_MISSING_MASK
    schema_version: str = field(default=MARKER_SCHEMA_VERSION, init=False)
    product_type: str = field(default=MARKER_PRODUCT_TYPE, init=False)

    def __post_init__(self) -> None:
        if not self.markers:
            raise ValueError("an observation marker product cannot be empty")
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))


@dataclass(frozen=True)
class ObservationProfileVariable:
    name: str
    units: str
    source_dtype: str
    values: np.ndarray
    missing_value_mask: np.ndarray
    qc_variable: str | None = None
    qc_source_dtype: str | None = None
    qc_flags: np.ndarray | None = None
    qc_missing_value_mask: np.ndarray | None = None

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        mask = np.asarray(self.missing_value_mask)
        if values.ndim != 1 or mask.shape != values.shape:
            raise ValueError("profile values and masks must be aligned vectors")
        object.__setattr__(self, "values", _readonly_array(values))
        object.__setattr__(self, "missing_value_mask",
                           _readonly_array(mask.astype(bool)))
        qc_parts = (self.qc_variable, self.qc_source_dtype, self.qc_flags,
                    self.qc_missing_value_mask)
        if any(part is not None for part in qc_parts):
            if any(part is None for part in qc_parts):
                raise ValueError("QC name, dtype, flags and mask must travel together")
            qc_flags = np.asarray(self.qc_flags)
            qc_mask = np.asarray(self.qc_missing_value_mask)
            if qc_flags.ndim != 1 or qc_flags.shape != values.shape \
                    or qc_mask.shape != values.shape:
                raise ValueError("QC flags and masks must align with profile values")
            object.__setattr__(self, "qc_flags", _readonly_array(qc_flags))
            object.__setattr__(self, "qc_missing_value_mask",
                               _readonly_array(qc_mask.astype(bool)))


@dataclass(frozen=True)
class ObservationProfileProduct:
    dataset_identity: DatasetIdentity
    profile_identity: ObservationProfileIdentity
    coordinates: ObservationCoordinateMetadata
    spatial_reference: SpatialReference
    provenance: Mapping[str, Any]
    source_indices: tuple[int, ...]
    vertical_values: np.ndarray
    vertical_missing_value_mask: np.ndarray
    timestamps: np.ndarray
    timestamp_missing_value_mask: np.ndarray
    variables: tuple[ObservationProfileVariable, ...]
    coordinate_transform: CoordinateTransform = OBSERVATION_IDENTITY_TRANSFORM
    mask_semantics: MaskSemantics = OBSERVATION_MISSING_MASK
    schema_version: str = field(default=PROFILE_SCHEMA_VERSION, init=False)
    product_type: str = field(default=PROFILE_PRODUCT_TYPE, init=False)

    def __post_init__(self) -> None:
        count = len(self.source_indices)
        arrays = (self.vertical_values, self.vertical_missing_value_mask,
                  self.timestamps, self.timestamp_missing_value_mask)
        if any(np.asarray(array).ndim != 1
               or np.asarray(array).size != count for array in arrays):
            raise ValueError("profile coordinates must align with source indices")
        if not self.variables:
            raise ValueError("an observation profile product needs variables")
        if any(variable.values.size != count for variable in self.variables):
            raise ValueError("profile variables must align with source indices")
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))
        for name in ("vertical_values", "timestamps"):
            object.__setattr__(self, name,
                               _readonly_array(getattr(self, name)))
        for name in ("vertical_missing_value_mask",
                     "timestamp_missing_value_mask"):
            object.__setattr__(self, name, _readonly_array(
                np.asarray(getattr(self, name), dtype=bool)))


def _variable(dataset: xr.Dataset, name: str, sample_dimension: str,
              role: str) -> xr.DataArray:
    if name not in dataset.variables:
        raise ObservationValidationError(
            f"{role} {name!r} is absent from the decoded observation dataset")
    variable = dataset[name]
    if variable.dims != (sample_dimension,):
        raise ObservationValidationError(
            f"{role} {name!r} must use only sample dimension "
            f"{sample_dimension!r}; found {variable.dims!r}")
    return variable


def _values_and_mask(variable: xr.DataArray) -> tuple[np.ndarray, np.ndarray]:
    raw = np.asanyarray(variable.values)
    values = np.array(np.ma.getdata(raw), copy=True)
    mask = np.asarray(np.ma.getmaskarray(raw), dtype=bool)
    mask |= np.asarray(variable.isnull().values, dtype=bool)
    return values, mask


def _real_values(variable: xr.DataArray, role: str) -> tuple[np.ndarray, np.ndarray]:
    values, mask = _values_and_mask(variable)
    if (not np.issubdtype(values.dtype, np.number)
            or np.issubdtype(values.dtype, np.complexfloating)
            or np.issubdtype(values.dtype, np.bool_)):
        raise ObservationValidationError(
            f"{role} {variable.name!r} must contain real numeric values")
    if bool((~mask & ~np.isfinite(values)).any()):
        raise ObservationValidationError(
            f"{role} {variable.name!r} contains non-finite values that are "
            "not marked missing")
    return values, mask


def _identity_text(value: Any) -> str:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ObservationIdentityError(
                "an observation identity is not valid UTF-8") from exc
    return str(value)


def _identity_columns(dataset: xr.Dataset, descriptor: ObservationDatasetDescriptor
                      ) -> tuple[list[str | None], list[str | None]]:
    dimension = descriptor.sample_dimension
    platform = _variable(dataset, descriptor.coordinates.platform,
                         dimension, "platform identity")
    cycle = _variable(dataset, descriptor.coordinates.cycle,
                      dimension, "cycle/profile identity")
    platform_values, platform_mask = _values_and_mask(platform)
    cycle_values, cycle_mask = _values_and_mask(cycle)
    platforms = [None if platform_mask[index]
                 else _identity_text(platform_values[index])
                 for index in range(platform.size)]
    cycles = [None if cycle_mask[index]
              else _identity_text(cycle_values[index])
              for index in range(cycle.size)]
    return platforms, cycles


def _observation_context(dataset: xr.Dataset,
                         descriptor: ObservationDatasetDescriptor
                         ) -> tuple[dict[str, xr.DataArray],
                                    ObservationCoordinateMetadata]:
    if not isinstance(dataset, xr.Dataset):
        raise ObservationValidationError(
            "decoded observations must be an xarray.Dataset")
    dimension = descriptor.sample_dimension
    if dimension not in dataset.sizes or dataset.sizes[dimension] < 1:
        raise ObservationValidationError(
            f"sample dimension {dimension!r} is absent or empty")
    roles = descriptor.coordinates
    coordinates = {
        role: _variable(dataset, getattr(roles, role), dimension,
                        f"{role} coordinate")
        for role in ("platform", "cycle", "longitude", "latitude", "time",
                     "vertical")
    }
    _real_values(coordinates["longitude"], "longitude coordinate")
    _real_values(coordinates["latitude"], "latitude coordinate")
    _real_values(coordinates["vertical"], "vertical coordinate")
    if not np.issubdtype(coordinates["time"].dtype, np.datetime64):
        raise ObservationValidationError(
            f"time coordinate {roles.time!r} must be decoded to datetime64")
    units = {role: coordinates[role].attrs.get("units")
             for role in coordinates}
    dtypes = {role: str(coordinates[role].dtype) for role in coordinates}
    time = coordinates["time"]
    time_encoding = {
        "units": time.encoding.get("units", time.attrs.get("units")),
        "calendar": time.encoding.get("calendar", time.attrs.get("calendar")),
    }
    metadata = ObservationCoordinateMetadata(
        names=roles,
        sample_dimension=dimension,
        units=units,
        dtypes=dtypes,
        time_encoding=time_encoding,
        vertical_kind=descriptor.vertical.kind,
    )
    return coordinates, metadata


def _spatial_reference(descriptor: ObservationDatasetDescriptor
                       ) -> SpatialReference:
    return SpatialReference(crs=descriptor.crs,
                            vertical_positive=descriptor.vertical.positive)


def _scalar(value: Any) -> Any:
    return np.asarray(value).copy()[()]


def build_observation_markers(
        dataset: xr.Dataset,
        descriptor: ObservationDatasetDescriptor) -> ObservationMarkerProduct:
    """Group exact identities and choose source-row marker coordinates."""
    coordinates, metadata = _observation_context(dataset, descriptor)
    platforms, cycles = _identity_columns(dataset, descriptor)
    groups: OrderedDict[tuple[str, str], list[int]] = OrderedDict()
    for source_index, (platform, cycle) in enumerate(zip(platforms, cycles)):
        if platform is None or cycle is None or not platform or not cycle:
            raise ObservationIdentityError(
                f"source observation {source_index} has no exact platform "
                "and cycle/profile identity")
        groups.setdefault((platform, cycle), []).append(source_index)

    longitude, longitude_mask = _real_values(
        coordinates["longitude"], "longitude coordinate")
    latitude, latitude_mask = _real_values(
        coordinates["latitude"], "latitude coordinate")
    vertical, vertical_mask = _real_values(
        coordinates["vertical"], "vertical coordinate")
    timestamps, timestamp_mask = _values_and_mask(coordinates["time"])

    markers: list[ObservationMarker] = []
    for (platform, cycle), source_indices in groups.items():
        complete = [index for index in source_indices
                    if not (longitude_mask[index] or latitude_mask[index]
                            or timestamp_mask[index])]
        identity = ObservationProfileIdentity(platform, cycle)
        if not complete:
            raise ObservationValidationError(
                f"profile {platform!r}/{cycle!r} has no source row with "
                "longitude, latitude and time for a marker")
        valid_vertical = [index for index in source_indices
                          if not vertical_mask[index]]
        if not valid_vertical:
            raise ObservationValidationError(
                f"profile {platform!r}/{cycle!r} has no vertical values")
        representative = complete[0]
        selected_vertical = vertical[valid_vertical]
        markers.append(ObservationMarker(
            identity=identity,
            longitude=_scalar(longitude[representative]),
            latitude=_scalar(latitude[representative]),
            time_value=_scalar(timestamps[representative]),
            vertical_range=ObservationVerticalRange(
                minimum=_scalar(np.min(selected_vertical)),
                maximum=_scalar(np.max(selected_vertical)),
                valid_observation_count=len(valid_vertical),
                missing_observation_count=(len(source_indices)
                                           - len(valid_vertical)),
            ),
            representative_source_index=representative,
            source_indices=tuple(source_indices),
        ))

    return ObservationMarkerProduct(
        dataset_identity=descriptor.identity,
        coordinates=metadata,
        spatial_reference=_spatial_reference(descriptor),
        provenance=descriptor.provenance,
        grouping=MarkerGroupingMetadata(
            grouping_keys=(descriptor.coordinates.platform,
                           descriptor.coordinates.cycle),
            representative_policy=(
                "first source row in dataset order with non-missing longitude, "
                "latitude and time; no coordinate averaging"),
            original_observation_count=int(dataset.sizes[
                descriptor.sample_dimension]),
            delivered_marker_count=len(markers),
        ),
        markers=tuple(markers),
    )


def build_observation_profile(
        dataset: xr.Dataset,
        descriptor: ObservationDatasetDescriptor,
        selection: ObservationProfileSelection) -> ObservationProfileProduct:
    """Select one exact identity and preserve its source-row profile."""
    coordinates, metadata = _observation_context(dataset, descriptor)
    platforms, cycles = _identity_columns(dataset, descriptor)
    wanted = selection.identity
    source_indices = tuple(
        index for index, (platform, cycle) in enumerate(zip(platforms, cycles))
        if platform == wanted.platform_id and cycle == wanted.cycle
    )
    if not source_indices:
        raise ObservationIdentityError(
            f"no observations match platform {wanted.platform_id!r} and "
            f"cycle/profile {wanted.cycle!r}")
    selected = np.asarray(source_indices, dtype=np.intp)

    vertical, vertical_mask = _real_values(
        coordinates["vertical"], "vertical coordinate")
    timestamps, timestamp_mask = _values_and_mask(coordinates["time"])
    if bool(vertical_mask[selected].all()):
        raise ObservationValidationError(
            f"profile {wanted.platform_id!r}/{wanted.cycle!r} has no vertical "
            "values")

    variables: list[ObservationProfileVariable] = []
    has_valid_measurement = False
    for name in selection.variables:
        if name not in dataset.data_vars:
            available = ", ".join(sorted(str(value)
                                         for value in dataset.data_vars)) or "none"
            raise ObservationVariableError(
                f"observation variable {name!r} is unavailable; available "
                f"variables: {available}")
        variable = _variable(dataset, name, descriptor.sample_dimension,
                             "observation variable")
        values, missing = _real_values(variable, "observation variable")
        units = variable.attrs.get("units")
        if not isinstance(units, str) or not units.strip():
            raise ObservationVariableError(
                f"observation variable {name!r} has no declared units")
        selected_values = values[selected]
        selected_missing = missing[selected]
        has_valid_measurement |= bool((~selected_missing).any())

        qc_name = descriptor.qc_variables.get(name)
        qc_dtype = None
        qc_values = None
        qc_missing = None
        if qc_name is not None:
            qc = _variable(dataset, qc_name, descriptor.sample_dimension,
                           f"QC variable for {name!r}")
            all_qc_values, all_qc_missing = _values_and_mask(qc)
            qc_dtype = str(qc.dtype)
            qc_values = all_qc_values[selected]
            qc_missing = all_qc_missing[selected]

        variables.append(ObservationProfileVariable(
            name=name,
            units=units,
            source_dtype=str(variable.dtype),
            values=selected_values,
            missing_value_mask=selected_missing,
            qc_variable=qc_name,
            qc_source_dtype=qc_dtype,
            qc_flags=qc_values,
            qc_missing_value_mask=qc_missing,
        ))

    if not has_valid_measurement:
        raise AllMissingObservationError(
            f"profile {wanted.platform_id!r}/{wanted.cycle!r} has no valid "
            "values for the requested variables")

    return ObservationProfileProduct(
        dataset_identity=descriptor.identity,
        profile_identity=wanted,
        coordinates=metadata,
        spatial_reference=_spatial_reference(descriptor),
        provenance=descriptor.provenance,
        source_indices=source_indices,
        vertical_values=vertical[selected],
        vertical_missing_value_mask=vertical_mask[selected],
        timestamps=timestamps[selected],
        timestamp_missing_value_mask=timestamp_mask[selected],
        variables=tuple(variables),
    )
