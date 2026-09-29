"""Pure observation marker and exact-profile scientific products."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

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

if TYPE_CHECKING:
    from ingestion.query import (
        ObservationProfile as StoredObservationProfile,
        ProfileMarker as StoredProfileMarker,
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

OBSERVATION_RECORD_TRANSFORM = CoordinateTransform(
    kind="s3-observation-record",
    horizontal="longitude, latitude and marker time supplied by the S3 "
               "ProfileMarker contract; S4 does not average, reproject or "
               "re-wrap them",
    vertical="source-order vertical values supplied by the S3 "
             "ObservationProfile contract; S4 does not convert, sort or "
             "interpolate them",
)

OBSERVATION_MISSING_MASK = MaskSemantics(
    true_means="the source observation has no decoded value",
    sources=("NaN or NaT after decoding", "masked array element"),
    masked_values="not scientific values; consumers must apply the mask",
)

OBSERVATION_RECORD_MISSING_MASK = MaskSemantics(
    true_means="the S3 observation record has no scientific value",
    sources=("None in an S3 profile record", "NaN in a numeric record value"),
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
class ObservationRecordDescriptor:
    """Semantics S3 records do not carry and S4 must never guess."""

    identity: DatasetIdentity
    spatial_reference: SpatialReference
    vertical_kind: str
    vertical_coordinate: str
    vertical_units: str
    provenance: Mapping[str, Any]
    sample_dimension: str = "observation_record"

    def __post_init__(self) -> None:
        if self.vertical_kind not in VERTICAL_KINDS:
            raise InvalidRequestError(
                f"vertical kind must be one of {VERTICAL_KINDS}, not "
                f"{self.vertical_kind!r}")
        if (not isinstance(self.vertical_coordinate, str)
                or not self.vertical_coordinate.strip()):
            raise InvalidRequestError(
                "an observation-record vertical coordinate is required")
        if (not isinstance(self.vertical_units, str)
                or not self.vertical_units.strip()):
            raise InvalidRequestError(
                "observation-record vertical units are required")
        if not isinstance(self.sample_dimension, str) \
                or not self.sample_dimension.strip():
            raise InvalidRequestError(
                "an observation-record sample dimension is required")
        if not isinstance(self.provenance, Mapping):
            raise InvalidRequestError("provenance must be a mapping")
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
    dtypes: Mapping[str, str | None]
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
class SkippedObservationProfile:
    identity: ObservationProfileIdentity
    source_indices: tuple[int, ...]
    reason: str

    def __post_init__(self) -> None:
        if not self.source_indices:
            raise ValueError("a skipped profile must identify its source rows")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("a skipped profile needs an actionable reason")


@dataclass(frozen=True)
class MarkerGroupingMetadata:
    grouping_keys: tuple[str, str]
    representative_policy: str
    original_observation_count: int
    delivered_marker_count: int
    skipped_profile_count: int


@dataclass(frozen=True)
class ObservationMarkerProduct:
    dataset_identity: DatasetIdentity
    coordinates: ObservationCoordinateMetadata
    spatial_reference: SpatialReference
    provenance: Mapping[str, Any]
    grouping: MarkerGroupingMetadata
    markers: tuple[ObservationMarker, ...]
    skipped_profiles: tuple[SkippedObservationProfile, ...]
    coordinate_transform: CoordinateTransform = OBSERVATION_IDENTITY_TRANSFORM
    mask_semantics: MaskSemantics = OBSERVATION_MISSING_MASK
    schema_version: str = field(default=MARKER_SCHEMA_VERSION, init=False)
    product_type: str = field(default=MARKER_PRODUCT_TYPE, init=False)

    def __post_init__(self) -> None:
        if self.grouping.delivered_marker_count != len(self.markers):
            raise ValueError("delivered marker count must match marker records")
        if self.grouping.skipped_profile_count != len(self.skipped_profiles):
            raise ValueError("skipped profile count must match skipped records")
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))


@dataclass(frozen=True)
class ObservationProfileVariable:
    name: str
    units: str | None
    source_dtype: str | None
    values: np.ndarray
    missing_value_mask: np.ndarray
    qc_variable: str | None = None
    qc_source_dtype: str | None = None
    qc_flags: np.ndarray | None = None
    qc_missing_value_mask: np.ndarray | None = None
    qc_flag_values: tuple[str | int | float | bool | None, ...] | None = None
    qc_flag_meanings: str | None = None
    qc_conventions: str | None = None

    def __post_init__(self) -> None:
        values = np.asarray(self.values)
        mask = np.asarray(self.missing_value_mask)
        if values.ndim != 1 or mask.shape != values.shape:
            raise ValueError("profile values and masks must be aligned vectors")
        object.__setattr__(self, "values", _readonly_array(values))
        object.__setattr__(self, "missing_value_mask",
                           _readonly_array(mask.astype(bool)))
        qc_parts = (self.qc_variable, self.qc_flags,
                    self.qc_missing_value_mask)
        if any(part is not None for part in qc_parts):
            if any(part is None for part in qc_parts):
                raise ValueError("QC name, flags and mask must travel together")
            qc_flags = np.asarray(self.qc_flags)
            qc_mask = np.asarray(self.qc_missing_value_mask)
            if qc_flags.ndim != 1 or qc_flags.shape != values.shape \
                    or qc_mask.shape != values.shape:
                raise ValueError("QC flags and masks must align with profile values")
            object.__setattr__(self, "qc_flags", _readonly_array(qc_flags))
            object.__setattr__(self, "qc_missing_value_mask",
                               _readonly_array(qc_mask.astype(bool)))
        qc_metadata = (self.qc_flag_values, self.qc_flag_meanings,
                       self.qc_conventions, self.qc_source_dtype)
        if self.qc_variable is None and any(value is not None
                                            for value in qc_metadata):
            raise ValueError("QC vocabulary metadata requires a QC variable")
        if self.qc_flag_values is not None:
            frozen = _frozen_mapping(
                {"values": self.qc_flag_values})["values"]
            object.__setattr__(self, "qc_flag_values",
                               frozen)


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
    if isinstance(value, float) and np.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def _qc_scalar(variable: xr.DataArray, attribute: str, value: Any
               ) -> str | int | float | bool:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ObservationValidationError(
                f"QC attribute {attribute!r} on {variable.name!r} is not "
                "valid UTF-8") from exc
    if not isinstance(value, (str, int, float, bool)):
        raise ObservationValidationError(
            f"QC attribute {attribute!r} on {variable.name!r} must contain "
            "scalar text, numbers or booleans")
    if isinstance(value, float) and not np.isfinite(value):
        raise ObservationValidationError(
            f"QC attribute {attribute!r} on {variable.name!r} contains a "
            "non-finite value")
    return value


def _qc_flag_values(variable: xr.DataArray
                    ) -> tuple[str | int | float | bool, ...] | None:
    if "flag_values" not in variable.attrs:
        return None
    values = np.asarray(variable.attrs["flag_values"], dtype=object)
    if values.ndim > 1:
        raise ObservationValidationError(
            f"QC attribute 'flag_values' on {variable.name!r} must be a "
            "scalar or vector")
    flattened = values.reshape(-1)
    return tuple(_qc_scalar(variable, "flag_values", value)
                 for value in flattened)


def _optional_qc_text(variable: xr.DataArray, attribute: str) -> str | None:
    if attribute not in variable.attrs:
        return None
    value = _qc_scalar(variable, attribute, variable.attrs[attribute])
    if not isinstance(value, str):
        raise ObservationValidationError(
            f"QC attribute {attribute!r} on {variable.name!r} must be text")
    return value


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
    for source_index, (platform, cycle) in enumerate(
            zip(platforms, cycles, strict=True)):
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
    skipped: list[SkippedObservationProfile] = []
    for (platform, cycle), source_indices in groups.items():
        complete = [index for index in source_indices
                    if not (longitude_mask[index] or latitude_mask[index]
                            or timestamp_mask[index])]
        identity = ObservationProfileIdentity(platform, cycle)
        if not complete:
            skipped.append(SkippedObservationProfile(
                identity=identity,
                source_indices=tuple(source_indices),
                reason=("no source row has complete longitude, latitude "
                        "and time"),
            ))
            continue
        valid_vertical = [index for index in source_indices
                          if not vertical_mask[index]]
        if not valid_vertical:
            skipped.append(SkippedObservationProfile(
                identity=identity,
                source_indices=tuple(source_indices),
                reason="no non-missing vertical values",
            ))
            continue
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

    if not markers:
        reasons = "; ".join(
            f"{item.identity.platform_id!r}/{item.identity.cycle!r}: "
            f"{item.reason}" for item in skipped)
        raise ObservationValidationError(
            f"no observation marker can be built; skipped profiles: {reasons}")

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
            skipped_profile_count=len(skipped),
        ),
        markers=tuple(markers),
        skipped_profiles=tuple(skipped),
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
        index for index, (platform, cycle) in enumerate(
            zip(platforms, cycles, strict=True))
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
        qc_flag_values = None
        qc_flag_meanings = None
        qc_conventions = None
        if qc_name is not None:
            qc = _variable(dataset, qc_name, descriptor.sample_dimension,
                           f"QC variable for {name!r}")
            all_qc_values, all_qc_missing = _values_and_mask(qc)
            qc_dtype = str(qc.dtype)
            qc_values = all_qc_values[selected]
            qc_missing = all_qc_missing[selected]
            qc_flag_values = _qc_flag_values(qc)
            qc_flag_meanings = _optional_qc_text(qc, "flag_meanings")
            qc_conventions = _optional_qc_text(qc, "conventions")

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
            qc_flag_values=qc_flag_values,
            qc_flag_meanings=qc_flag_meanings,
            qc_conventions=qc_conventions,
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


def _record_identity(identity: Any) -> ObservationProfileIdentity:
    return ObservationProfileIdentity(
        platform_id=identity.platform_id,
        cycle=identity.cycle,
    )


def _require_record_version(identity: Any,
                            descriptor: ObservationRecordDescriptor) -> None:
    if identity.dataset_version_id != descriptor.identity.dataset_version_id:
        raise ObservationIdentityError(
            f"S3 profile belongs to dataset version "
            f"{identity.dataset_version_id!r}, not descriptor version "
            f"{descriptor.identity.dataset_version_id!r}")


def _record_numeric(values: tuple[Any, ...], role: str
                    ) -> tuple[np.ndarray, np.ndarray]:
    missing = np.zeros(len(values), dtype=bool)
    valid: list[int | float] = []
    for index, value in enumerate(values):
        if value is None or (isinstance(value, float) and np.isnan(value)):
            missing[index] = True
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not np.isfinite(value)):
            raise ObservationValidationError(
                f"{role} from the S3 observation record must contain finite "
                "real numbers or explicit missing values")
        valid.append(value)
    dtype = np.asarray(valid).dtype if valid else np.dtype("float64")
    output = np.zeros(len(values), dtype=dtype)
    valid_position = 0
    for index in np.flatnonzero(~missing):
        output[index] = valid[valid_position]
        valid_position += 1
    return output, missing


def _record_text(values: tuple[Any, ...]
                 ) -> tuple[np.ndarray, np.ndarray]:
    output = np.empty(len(values), dtype=object)
    missing = np.zeros(len(values), dtype=bool)
    for index, value in enumerate(values):
        if value is None:
            output[index] = ""
            missing[index] = True
        else:
            output[index] = value
    return output, missing


def _record_coordinate_metadata(
        profile: StoredObservationProfile,
        descriptor: ObservationRecordDescriptor) -> ObservationCoordinateMetadata:
    names = ObservationCoordinateRoles(
        platform="platform_id",
        cycle="cycle",
        longitude="longitude",
        latitude="latitude",
        time=profile.time_coordinate,
        vertical=profile.depth_coordinate,
    )
    return ObservationCoordinateMetadata(
        names=names,
        sample_dimension=descriptor.sample_dimension,
        units={
            "platform": None,
            "cycle": None,
            "longitude": "degrees_east",
            "latitude": "degrees_north",
            "time": None,
            "vertical": profile.depth_units,
        },
        dtypes={
            "platform": None,
            "cycle": None,
            "longitude": None,
            "latitude": None,
            "time": None,
            "vertical": None,
        },
        time_encoding={"units": None, "calendar": None},
        vertical_kind=descriptor.vertical_kind,
    )


def _empty_record_coordinate_metadata(
        descriptor: ObservationRecordDescriptor) -> ObservationCoordinateMetadata:
    """Describe a valid zero-match search without inventing profile values."""
    return ObservationCoordinateMetadata(
        names=ObservationCoordinateRoles(
            platform="platform_id",
            cycle="cycle",
            longitude="longitude",
            latitude="latitude",
            time="time",
            vertical=descriptor.vertical_coordinate,
        ),
        sample_dimension=descriptor.sample_dimension,
        units={
            "platform": None,
            "cycle": None,
            "longitude": "degrees_east",
            "latitude": "degrees_north",
            "time": None,
            "vertical": descriptor.vertical_units,
        },
        dtypes={name: None for name in (
            "platform", "cycle", "longitude", "latitude", "time", "vertical")},
        time_encoding={"units": None, "calendar": None},
        vertical_kind=descriptor.vertical_kind,
    )


def build_observation_markers_from_records(
        records: tuple[tuple[StoredProfileMarker,
                             StoredObservationProfile], ...],
        descriptor: ObservationRecordDescriptor) -> ObservationMarkerProduct:
    """Build the existing marker envelope from immutable S3 records."""
    if not records:
        return ObservationMarkerProduct(
            dataset_identity=descriptor.identity,
            coordinates=_empty_record_coordinate_metadata(descriptor),
            spatial_reference=descriptor.spatial_reference,
            provenance=descriptor.provenance,
            grouping=MarkerGroupingMetadata(
                grouping_keys=("platform_id", "cycle"),
                representative_policy=(
                    "marker longitude, latitude and time are supplied by the S3 "
                    "ProfileMarker record; no records matched this search"),
                original_observation_count=0,
                delivered_marker_count=0,
                skipped_profile_count=0,
            ),
            markers=(),
            skipped_profiles=(),
            coordinate_transform=OBSERVATION_RECORD_TRANSFORM,
            mask_semantics=OBSERVATION_RECORD_MISSING_MASK,
        )

    markers: list[ObservationMarker] = []
    skipped: list[SkippedObservationProfile] = []
    delivered_profiles: list[StoredObservationProfile] = []
    original_observation_count = 0
    for marker_record, profile_record in records:
        _require_record_version(marker_record.identity, descriptor)
        _require_record_version(profile_record.identity, descriptor)
        if marker_record.identity != profile_record.identity:
            raise ObservationIdentityError(
                "S3 marker and profile records have different identities")
        source_indices = tuple(range(len(profile_record.depth_values)))
        original_observation_count += len(source_indices)
        vertical, vertical_missing = _record_numeric(
            profile_record.depth_values, "profile vertical values")
        identity = _record_identity(marker_record.identity)
        valid_vertical = vertical[~vertical_missing]
        if valid_vertical.size == 0:
            skipped.append(SkippedObservationProfile(
                identity=identity,
                source_indices=source_indices,
                reason="no non-missing vertical values in the S3 profile record",
            ))
            continue
        delivered_profiles.append(profile_record)
        markers.append(ObservationMarker(
            identity=identity,
            longitude=marker_record.longitude,
            latitude=marker_record.latitude,
            time_value=marker_record.observed_at,
            vertical_range=ObservationVerticalRange(
                minimum=np.min(valid_vertical).item(),
                maximum=np.max(valid_vertical).item(),
                valid_observation_count=int(valid_vertical.size),
                missing_observation_count=int(vertical_missing.sum()),
            ),
            representative_source_index=0,
            source_indices=source_indices,
        ))

    if not markers:
        reasons = "; ".join(
            f"{item.identity.platform_id!r}/{item.identity.cycle!r}: "
            f"{item.reason}" for item in skipped)
        raise ObservationValidationError(
            f"no observation marker can be built; skipped profiles: {reasons}")

    first = delivered_profiles[0]
    coordinate_signature = (
        first.depth_coordinate, first.depth_units, first.time_coordinate)
    if any((profile.depth_coordinate, profile.depth_units,
            profile.time_coordinate) != coordinate_signature
           for profile in delivered_profiles[1:]):
        raise ObservationValidationError(
            "S3 profile records in one marker product must share vertical and "
            "time coordinate semantics")
    return ObservationMarkerProduct(
        dataset_identity=descriptor.identity,
        coordinates=_record_coordinate_metadata(
            first, descriptor),
        spatial_reference=descriptor.spatial_reference,
        provenance=descriptor.provenance,
        grouping=MarkerGroupingMetadata(
            grouping_keys=("platform_id", "cycle"),
            representative_policy=(
                "marker longitude, latitude and time are supplied by the S3 "
                "ProfileMarker record; source index zero anchors the companion "
                "S3 profile-record sequence and is not a coordinate reduction"),
            original_observation_count=original_observation_count,
            delivered_marker_count=len(markers),
            skipped_profile_count=len(skipped),
        ),
        markers=tuple(markers),
        skipped_profiles=tuple(skipped),
        coordinate_transform=OBSERVATION_RECORD_TRANSFORM,
        mask_semantics=OBSERVATION_RECORD_MISSING_MASK,
    )


def build_observation_profile_from_record(
        profile: StoredObservationProfile,
        descriptor: ObservationRecordDescriptor,
        selection: ObservationProfileSelection) -> ObservationProfileProduct:
    """Build the existing exact-profile envelope from one S3 record."""
    _require_record_version(profile.identity, descriptor)
    identity = _record_identity(profile.identity)
    if identity != selection.identity:
        raise ObservationIdentityError(
            f"S3 profile {identity.platform_id!r}/{identity.cycle!r} does not "
            "match the requested exact identity")

    vertical, vertical_missing = _record_numeric(
        profile.depth_values, "profile vertical values")
    if bool(vertical_missing.all()):
        raise ObservationValidationError(
            f"profile {identity.platform_id!r}/{identity.cycle!r} has no "
            "vertical values")
    timestamps, timestamp_missing = _record_text(profile.timestamps)
    available = {variable.name: variable for variable in profile.variables}
    requested: list[ObservationProfileVariable] = []
    has_valid_measurement = False
    for name in selection.variables:
        source = available.get(name)
        if source is None:
            names = ", ".join(sorted(available)) or "none"
            raise ObservationVariableError(
                f"observation variable {name!r} is unavailable; available "
                f"variables: {names}")
        values, missing = _record_numeric(
            source.values, f"observation variable {name!r}")
        has_valid_measurement |= bool((~missing).any())

        qc_values = None
        qc_missing = None
        if source.quality_control is not None:
            qc_values, qc_missing = _record_text(source.quality_control)

        requested.append(ObservationProfileVariable(
            name=name,
            units=source.units,
            source_dtype=None,
            values=values,
            missing_value_mask=missing,
            qc_variable=source.quality_control_name,
            qc_source_dtype=None,
            qc_flags=qc_values,
            qc_missing_value_mask=qc_missing,
            qc_flag_values=source.qc_flag_values,
            qc_flag_meanings=source.qc_flag_meanings,
            qc_conventions=source.qc_conventions,
        ))

    if not has_valid_measurement:
        raise AllMissingObservationError(
            f"profile {identity.platform_id!r}/{identity.cycle!r} has no valid "
            "values for the requested variables")

    return ObservationProfileProduct(
        dataset_identity=descriptor.identity,
        profile_identity=identity,
        coordinates=_record_coordinate_metadata(
            profile, descriptor),
        spatial_reference=descriptor.spatial_reference,
        provenance=descriptor.provenance,
        source_indices=tuple(range(len(profile.depth_values))),
        vertical_values=vertical,
        vertical_missing_value_mask=vertical_missing,
        timestamps=timestamps,
        timestamp_missing_value_mask=timestamp_missing,
        variables=tuple(requested),
        coordinate_transform=OBSERVATION_RECORD_TRANSFORM,
        mask_semantics=OBSERVATION_RECORD_MISSING_MASK,
    )
