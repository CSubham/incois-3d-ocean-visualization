"""Renderer-independent domain contracts for scalar-field processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from processing.errors import InvalidRequestError, PointBudgetError


PRODUCT_SCHEMA_VERSION = "s4.sampled-scalar-point-field/1.0"
PRODUCT_TYPE = "sampled_scalar_point_field"
SAMPLING_POLICY = "evenly-spaced-flat-index-v1"
VERTICAL_POSITIVE = ("down", "up")


def _frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """A deep, read-only copy restricted to JSON-compatible values.

    Anything else could be mutated behind the product's back or would not
    survive a cross-process binding, so it is refused rather than carried.
    """
    def freeze(item: Any, path: str) -> Any:
        if isinstance(item, Mapping):
            frozen = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise InvalidRequestError(
                        f"{path} has a non-text key {key!r}")
                frozen[key] = freeze(child, f"{path}.{key}")
            return MappingProxyType(frozen)
        if isinstance(item, (list, tuple)):
            return tuple(freeze(child, f"{path}[{position}]")
                         for position, child in enumerate(item))
        if isinstance(item, np.generic) and not isinstance(
                item, (np.datetime64, np.timedelta64)):
            item = item.item()
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float):
            if not isfinite(item):
                raise InvalidRequestError(
                    f"{path} is {item!r}, which has no JSON representation")
            return item
        raise InvalidRequestError(
            f"{path} holds a {type(item).__name__}; only text, numbers, "
            "booleans, null, lists and mappings are carried")

    return freeze(dict(value), "metadata")


def _readonly_array(value: np.ndarray) -> np.ndarray:
    copied = np.array(value, copy=True)
    copied.setflags(write=False)
    return copied


@dataclass(frozen=True)
class CoordinateRoles:
    """Dataset names that explicitly identify each scientific coordinate."""

    time: str
    depth: str
    latitude: str
    longitude: str

    def __post_init__(self) -> None:
        names = (self.time, self.depth, self.latitude, self.longitude)
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise InvalidRequestError(
                "time, depth, latitude and longitude coordinate names are "
                "all required")
        if len(set(names)) != len(names):
            raise InvalidRequestError(
                "coordinate roles must refer to four distinct dataset names")


@dataclass(frozen=True)
class DatasetIdentity:
    """Stable identity of the managed dataset version being processed.

    ``dataset_version_id`` is the immutable reference S3 hands out for one
    stored version, not a free-form label: two products with the same value
    were built from the same stored array.
    """

    dataset_id: str
    dataset_version_id: str

    def __post_init__(self) -> None:
        for name in ("dataset_id", "dataset_version_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidRequestError(
                    f"{name} is required for an auditable product")


@dataclass(frozen=True)
class SpatialReference:
    """Declared horizontal and vertical reference of the source grid.

    Supplied with the grid rather than guessed from coordinate names or
    values. Sample data uses more than one vertical convention, so the
    direction of increasing depth is never assumed.
    """

    crs: str
    vertical_positive: str

    def __post_init__(self) -> None:
        if not isinstance(self.crs, str) or not self.crs.strip():
            raise InvalidRequestError(
                "a coordinate reference system must be declared")
        if self.vertical_positive not in VERTICAL_POSITIVE:
            raise InvalidRequestError(
                f"vertical_positive must be one of {VERTICAL_POSITIVE}, "
                f"not {self.vertical_positive!r}")


@dataclass(frozen=True)
class ScalarGridDescriptor:
    """Explicit semantics and provenance supplied with a decoded grid."""

    identity: DatasetIdentity
    coordinates: CoordinateRoles
    spatial_reference: SpatialReference
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Mapping):
            raise InvalidRequestError("provenance must be a mapping")
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))
        recorded = self.provenance.get("import_id")
        if (recorded is not None
                and recorded != self.identity.dataset_version_id):
            raise InvalidRequestError(
                f"provenance import_id {recorded!r} contradicts "
                f"dataset_version_id {self.identity.dataset_version_id!r}")


@dataclass(frozen=True)
class GeographicBounds:
    """Inclusive bounds expressed in the source longitude convention."""

    west: float
    east: float
    south: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.east, self.south, self.north)
        if not all(isfinite(float(value)) for value in values):
            raise InvalidRequestError("geographic bounds must all be finite")
        if self.south > self.north:
            raise InvalidRequestError(
                "south must be less than or equal to north")
        if self.west > self.east:
            raise InvalidRequestError(
                "west must be less than or equal to east; antimeridian-"
                "crossing requests require an explicit policy and are not "
                "supported by this subsetter")


@dataclass(frozen=True)
class DepthBounds:
    """Inclusive depth bounds in the source coordinate's units."""

    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if not isfinite(float(self.minimum)) or not isfinite(float(self.maximum)):
            raise InvalidRequestError("depth bounds must be finite")
        if self.minimum > self.maximum:
            raise InvalidRequestError(
                "minimum depth must be less than or equal to maximum depth")


@dataclass(frozen=True)
class ScalarSelection:
    """One variable, one exact source time and bounded spatial/depth ranges."""

    variable: str
    time: Any
    area: GeographicBounds
    depth: DepthBounds

    def __post_init__(self) -> None:
        if not isinstance(self.variable, str) or not self.variable.strip():
            raise InvalidRequestError("one scalar variable name is required")
        if self.time is None:
            raise InvalidRequestError(
                "one exact source time value is required")


@dataclass(frozen=True)
class SamplingRequest:
    """A declared point budget and the supported deterministic policy."""

    maximum_points: int
    policy: str = SAMPLING_POLICY

    def __post_init__(self) -> None:
        if isinstance(self.maximum_points, bool) or not isinstance(
                self.maximum_points, int) or self.maximum_points < 1:
            raise PointBudgetError("maximum_points must be a positive integer")
        if self.policy != SAMPLING_POLICY:
            raise PointBudgetError(
                f"unsupported sampling policy {self.policy!r}; expected "
                f"{SAMPLING_POLICY!r}")


@dataclass(frozen=True)
class ProductIdentity:
    dataset_id: str
    dataset_version_id: str
    variable: str
    time_coordinate: str
    time_value: Any


@dataclass(frozen=True)
class CoordinateMetadata:
    """Coordinate names, dimensions, units, storage types and time encoding.

    ``time_encoding`` holds the source's declared ``units`` and ``calendar``;
    a value of None means the source did not declare it, not that a default
    was assumed.
    """

    names: CoordinateRoles
    dimensions: Mapping[str, str]
    units: Mapping[str, str | None]
    dtypes: Mapping[str, str]
    time_encoding: Mapping[str, str | None]

    def __post_init__(self) -> None:
        for name in ("dimensions", "units", "dtypes", "time_encoding"):
            object.__setattr__(self, name, _frozen_mapping(getattr(self, name)))


@dataclass(frozen=True)
class CoordinateTransform:
    """What was done to source coordinates before delivery."""

    kind: str
    horizontal: str
    vertical: str


IDENTITY_TRANSFORM = CoordinateTransform(
    kind="identity",
    horizontal="source longitude and latitude values in the declared CRS; "
               "not reprojected and not re-wrapped",
    vertical="source depth values in source units and the declared positive "
             "direction; no exaggeration applied",
)


@dataclass(frozen=True)
class MaskSemantics:
    """How to read ``missing_value_mask`` and the values it covers."""

    true_means: str
    sources: tuple[str, ...]
    masked_values: str


MISSING_VALUE_MASK = MaskSemantics(
    true_means="the source cell has no valid value",
    sources=("NaN after CF decoding", "masked array element"),
    masked_values="not scientific values; consumers must apply the mask and "
                  "exclude them from display and ranges",
)


@dataclass(frozen=True)
class DimensionMetadata:
    """Source order plus the semantic order used for deterministic traversal."""

    source_order: tuple[str, ...]
    semantic_order: tuple[str, str, str]
    subset_shape: tuple[int, int, int]


@dataclass(frozen=True)
class PhysicalRange:
    minimum: int | float | None
    maximum: int | float | None
    valid_point_count: int
    missing_point_count: int


@dataclass(frozen=True)
class SourceCellIndex:
    """Zero-based positions in each coordinate axis of the source dataset."""

    time: int
    depth: int
    latitude: int
    longitude: int


@dataclass(frozen=True)
class SamplingMetadata:
    """The sampling applied, with cell and valid-value counts kept apart.

    ``original_point_count`` and ``delivered_point_count`` count cells,
    masked or not; the ``*_valid_point_count`` fields count only cells with
    a valid value.
    """

    policy: str
    parameters: Mapping[str, Any]
    maximum_points: int
    original_point_count: int
    original_valid_point_count: int
    delivered_point_count: int
    delivered_valid_point_count: int
    omitted_point_count: int
    is_lossy: bool
    selected_subset_flat_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters",
                           _frozen_mapping(self.parameters))


@dataclass(frozen=True)
class PointFieldData:
    longitude: np.ndarray
    latitude: np.ndarray
    depth: np.ndarray
    values: np.ndarray
    missing_value_mask: np.ndarray
    source_indices: tuple[SourceCellIndex, ...]

    def __post_init__(self) -> None:
        arrays = (self.longitude, self.latitude, self.depth, self.values,
                  self.missing_value_mask)
        if any(np.asarray(array).ndim != 1 for array in arrays):
            raise ValueError("point-field arrays must be one-dimensional")
        lengths = {np.asarray(array).size for array in arrays}
        lengths.add(len(self.source_indices))
        if len(lengths) != 1:
            raise ValueError("point-field arrays and source indices must align")
        for name in ("longitude", "latitude", "depth", "values",
                     "missing_value_mask"):
            object.__setattr__(self, name,
                               _readonly_array(getattr(self, name)))


@dataclass(frozen=True)
class ScalarSubset:
    """A decoded, bounded scalar grid with original-axis traceability."""

    identity: ProductIdentity
    coordinates: CoordinateMetadata
    spatial_reference: SpatialReference
    source_dimensions: tuple[str, ...]
    semantic_dimensions: tuple[str, str, str]
    variable_units: str
    provenance: Mapping[str, Any]
    time_source_index: int
    depth_source_indices: tuple[int, ...]
    latitude_source_indices: tuple[int, ...]
    longitude_source_indices: tuple[int, ...]
    depth_values: np.ndarray
    latitude_values: np.ndarray
    longitude_values: np.ndarray
    values: np.ndarray
    missing_value_mask: np.ndarray

    def __post_init__(self) -> None:
        expected = (len(self.depth_source_indices),
                    len(self.latitude_source_indices),
                    len(self.longitude_source_indices))
        if np.asarray(self.values).shape != expected:
            raise ValueError("subset values do not match selected axes")
        if np.asarray(self.missing_value_mask).shape != expected:
            raise ValueError("subset mask does not match selected axes")
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))
        for name in ("depth_values", "latitude_values", "longitude_values",
                     "values", "missing_value_mask"):
            object.__setattr__(self, name,
                               _readonly_array(getattr(self, name)))


@dataclass(frozen=True)
class ScalarPointFieldProduct:
    """Versioned scientific envelope with no renderer or transport coupling."""

    identity: ProductIdentity
    coordinates: CoordinateMetadata
    spatial_reference: SpatialReference
    dimensions: DimensionMetadata
    variable_units: str
    source_dtype: str
    provenance: Mapping[str, Any]
    sampling: SamplingMetadata
    full_subset_range: PhysicalRange
    delivered_sample_range: PhysicalRange
    points: PointFieldData
    coordinate_transform: CoordinateTransform = IDENTITY_TRANSFORM
    mask_semantics: MaskSemantics = MISSING_VALUE_MASK
    schema_version: str = field(default=PRODUCT_SCHEMA_VERSION, init=False)
    product_type: str = field(default=PRODUCT_TYPE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))
