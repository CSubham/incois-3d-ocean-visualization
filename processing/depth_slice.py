"""Pure depth-slice products for rectilinear scalar scientific grids."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping

import numpy as np
import xarray as xr

from processing.domain import (
    IDENTITY_TRANSFORM, MISSING_VALUE_MASK, CoordinateMetadata,
    CoordinateTransform, GeographicBounds, MaskSemantics, PhysicalRange,
    ProductIdentity, ScalarGridDescriptor, ScalarSelection, SpatialReference,
    DepthBounds, _frozen_mapping, _readonly_array,
)
from processing.errors import (
    AllMissingSubsetError, DepthSelectionError, GridValidationError,
    InvalidRequestError,
)
from processing.point_field import physical_range
from processing.subsetter import subset_scalar_field


SLICE_SCHEMA_VERSION = "s4.depth-slice/1.0"
SLICE_PRODUCT_TYPE = "depth_slice"
EXACT_DEPTH_POLICY = "none"
LINEAR_DEPTH_POLICY = "linear"
DEPTH_POLICIES = (EXACT_DEPTH_POLICY, LINEAR_DEPTH_POLICY)

LINEAR_DEPTH_TRANSFORM = CoordinateTransform(
    kind="linear-depth-interpolation",
    horizontal="source longitude and latitude values in the declared CRS; "
               "not reprojected and not re-wrapped",
    vertical="requested depth linearly interpolated between the two recorded "
             "source depth levels; source indices, values and weights are "
             "declared in interpolation metadata",
)

SLICE_MISSING_MASK = MaskSemantics(
    true_means="the delivered slice cell has no valid value",
    sources=(
        "source cell missing at an exact selected depth",
        "either bracketing source cell missing during linear interpolation",
    ),
    masked_values="not scientific values; consumers must apply the mask and "
                  "exclude them from display and ranges",
)


@dataclass(frozen=True)
class DepthSliceSelection:
    variable: str
    time: Any
    area: GeographicBounds
    depth: float
    interpolation: str = EXACT_DEPTH_POLICY

    def __post_init__(self) -> None:
        if not isinstance(self.variable, str) or not self.variable.strip():
            raise InvalidRequestError("one scalar variable name is required")
        if self.time is None:
            raise InvalidRequestError("one exact source time value is required")
        if isinstance(self.depth, bool) or not isfinite(float(self.depth)):
            raise DepthSelectionError("slice depth must be finite")
        if self.interpolation not in DEPTH_POLICIES:
            raise DepthSelectionError(
                f"unsupported depth interpolation policy "
                f"{self.interpolation!r}; expected one of {DEPTH_POLICIES}")


@dataclass(frozen=True)
class DepthInterpolationMetadata:
    policy: str
    requested_depth: int | float
    delivered_depth: int | float
    source_depth_indices: tuple[int, ...]
    source_depth_values: tuple[int | float, ...]
    weights: tuple[float, ...]
    is_interpolated: bool

    def __post_init__(self) -> None:
        sizes = {len(self.source_depth_indices), len(self.source_depth_values),
                 len(self.weights)}
        if len(sizes) != 1 or not self.source_depth_indices:
            raise ValueError("slice source depths and weights must align")
        if self.is_interpolated and len(self.source_depth_indices) != 2:
            raise ValueError("linear interpolation requires two source depths")
        if not self.is_interpolated and len(self.source_depth_indices) != 1:
            raise ValueError("an exact slice requires one source depth")


@dataclass(frozen=True)
class DepthSliceDimensions:
    source_order: tuple[str, ...]
    semantic_order: tuple[str, str]
    slice_shape: tuple[int, int]


@dataclass(frozen=True)
class DepthSliceData:
    longitude: np.ndarray
    latitude: np.ndarray
    values: np.ndarray
    missing_value_mask: np.ndarray
    time_source_index: int
    latitude_source_indices: tuple[int, ...]
    longitude_source_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        longitude = np.asarray(self.longitude)
        latitude = np.asarray(self.latitude)
        values = np.asarray(self.values)
        mask = np.asarray(self.missing_value_mask)
        if longitude.ndim != 1 or latitude.ndim != 1:
            raise ValueError("slice longitude and latitude must be vectors")
        expected = (latitude.size, longitude.size)
        if values.shape != expected or mask.shape != expected:
            raise ValueError("slice values and mask must match its grid shape")
        if len(self.latitude_source_indices) != latitude.size \
                or len(self.longitude_source_indices) != longitude.size:
            raise ValueError("slice source indices must align with coordinates")
        for name in ("longitude", "latitude", "values",
                     "missing_value_mask"):
            object.__setattr__(self, name,
                               _readonly_array(getattr(self, name)))


@dataclass(frozen=True)
class DepthSliceProduct:
    identity: ProductIdentity
    coordinates: CoordinateMetadata
    spatial_reference: SpatialReference
    dimensions: DepthSliceDimensions
    variable_units: str
    source_dtype: str
    delivered_dtype: str
    provenance: Mapping[str, Any]
    interpolation: DepthInterpolationMetadata
    physical_range: PhysicalRange
    data: DepthSliceData
    coordinate_transform: CoordinateTransform = IDENTITY_TRANSFORM
    mask_semantics: MaskSemantics = MISSING_VALUE_MASK
    schema_version: str = field(default=SLICE_SCHEMA_VERSION, init=False)
    product_type: str = field(default=SLICE_PRODUCT_TYPE, init=False)

    def __post_init__(self) -> None:
        if self.dimensions.slice_shape != np.asarray(self.data.values).shape:
            raise ValueError("slice dimensions do not match delivered values")
        object.__setattr__(self, "provenance",
                           _frozen_mapping(self.provenance))


def _depth_values(dataset: xr.Dataset,
                  descriptor: ScalarGridDescriptor) -> np.ndarray:
    name = descriptor.coordinates.depth
    if name not in dataset.coords:
        raise GridValidationError(
            f"depth coordinate {name!r} is absent from dataset coordinates")
    coordinate = dataset.coords[name]
    values = np.asarray(coordinate.values)
    if coordinate.ndim != 1 or coordinate.size == 0:
        raise GridValidationError(
            f"depth coordinate {name!r} must be a non-empty vector")
    if (not np.issubdtype(values.dtype, np.number)
            or np.issubdtype(values.dtype, np.complexfloating)
            or np.issubdtype(values.dtype, np.bool_)
            or not bool(np.isfinite(values).all())):
        raise GridValidationError(
            f"depth coordinate {name!r} must contain finite real numbers")
    differences = np.diff(values)
    if differences.size and not (bool((differences > 0).all())
                                 or bool((differences < 0).all())):
        raise GridValidationError(
            f"depth coordinate {name!r} must be strictly ascending or "
            "descending for slice selection")
    return values


def _depth_plan(values: np.ndarray, selection: DepthSliceSelection
                ) -> tuple[tuple[int, ...], tuple[float, ...], bool]:
    requested = float(selection.depth)
    exact = np.flatnonzero(values == requested)
    if exact.size == 1:
        return (int(exact[0]),), (1.0,), False
    if exact.size > 1:
        raise DepthSelectionError(
            f"requested depth {selection.depth!r} matches multiple source "
            "levels")
    if selection.interpolation == EXACT_DEPTH_POLICY:
        available = tuple(value.item() for value in values)
        raise DepthSelectionError(
            f"requested depth {selection.depth!r} is not an existing source "
            f"level; available depths are {available}; request "
            f"{LINEAR_DEPTH_POLICY!r} interpolation explicitly to interpolate")

    lower = np.flatnonzero(values < requested)
    upper = np.flatnonzero(values > requested)
    if lower.size == 0 or upper.size == 0:
        raise DepthSelectionError(
            f"requested depth {selection.depth!r} lies outside source extent "
            f"[{np.min(values).item()}, {np.max(values).item()}]; linear "
            "interpolation never extrapolates")
    lower_index = int(lower[np.argmax(values[lower])])
    upper_index = int(upper[np.argmin(values[upper])])
    lower_value = float(values[lower_index])
    upper_value = float(values[upper_index])
    upper_weight = (requested - lower_value) / (upper_value - lower_value)
    return ((lower_index, upper_index),
            (1.0 - upper_weight, upper_weight), True)


def build_depth_slice(
        dataset: xr.Dataset,
        descriptor: ScalarGridDescriptor,
        selection: DepthSliceSelection,
        maximum_cells: int | None = None) -> DepthSliceProduct:
    """Select one exact level or explicitly interpolate between two levels."""
    values = _depth_values(dataset, descriptor)
    source_depth_indices, weights, interpolated = _depth_plan(
        values, selection)
    selected_depth_values = tuple(
        values[index].item() for index in source_depth_indices)
    subset = subset_scalar_field(
        dataset,
        descriptor,
        ScalarSelection(
            variable=selection.variable,
            time=selection.time,
            area=selection.area,
            depth=DepthBounds(
                minimum=min(selected_depth_values),
                maximum=max(selected_depth_values),
            ),
        ),
        maximum_cells=maximum_cells,
    )
    positions = {source_index: position for position, source_index
                 in enumerate(subset.depth_source_indices)}
    if any(index not in positions for index in source_depth_indices):
        raise GridValidationError(
            "slice depth selection does not match the scalar subset")

    if interpolated:
        lower = positions[source_depth_indices[0]]
        upper = positions[source_depth_indices[1]]
        lower_values = subset.values[lower]
        upper_values = subset.values[upper]
        output_dtype = np.result_type(subset.values.dtype, np.float64)
        delivered = (lower_values.astype(output_dtype) * weights[0]
                     + upper_values.astype(output_dtype) * weights[1])
        missing = (subset.missing_value_mask[lower]
                   | subset.missing_value_mask[upper])
        transform = LINEAR_DEPTH_TRANSFORM
        mask_semantics = SLICE_MISSING_MASK
    else:
        position = positions[source_depth_indices[0]]
        delivered = np.array(subset.values[position], copy=True)
        missing = np.array(subset.missing_value_mask[position], copy=True)
        transform = IDENTITY_TRANSFORM
        mask_semantics = MISSING_VALUE_MASK

    delivered_range = physical_range(delivered, missing)
    if delivered_range.valid_point_count == 0:
        raise AllMissingSubsetError(
            f"all {delivered_range.missing_point_count} cells of the depth "
            f"slice for {selection.variable!r} are missing")
    return DepthSliceProduct(
        identity=subset.identity,
        coordinates=subset.coordinates,
        spatial_reference=subset.spatial_reference,
        dimensions=DepthSliceDimensions(
            source_order=subset.source_dimensions,
            semantic_order=(subset.semantic_dimensions[1],
                            subset.semantic_dimensions[2]),
            slice_shape=tuple(int(size) for size in delivered.shape),
        ),
        variable_units=subset.variable_units,
        source_dtype=str(subset.values.dtype),
        delivered_dtype=str(delivered.dtype),
        provenance=subset.provenance,
        interpolation=DepthInterpolationMetadata(
            policy=selection.interpolation,
            requested_depth=selection.depth,
            delivered_depth=selection.depth,
            source_depth_indices=source_depth_indices,
            source_depth_values=selected_depth_values,
            weights=weights,
            is_interpolated=interpolated,
        ),
        physical_range=delivered_range,
        data=DepthSliceData(
            longitude=subset.longitude_values,
            latitude=subset.latitude_values,
            values=delivered,
            missing_value_mask=missing,
            time_source_index=subset.time_source_index,
            latitude_source_indices=subset.latitude_source_indices,
            longitude_source_indices=subset.longitude_source_indices,
        ),
        coordinate_transform=transform,
        mask_semantics=mask_semantics,
    )
