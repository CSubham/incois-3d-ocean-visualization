"""Horizontal current-vector slices built from two aligned scalar slices.

A current vector is its eastward and northward components on one grid at
one time and depth. Each component is sliced exactly as a scalar would be;
this module only proves the two describe the same cells and derives speed.
Direction is not derived here: the components themselves are delivered, so
nothing about the vector is lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from processing.depth_slice import DepthSliceProduct
from processing.domain import PhysicalRange, _readonly_array
from processing.errors import AllMissingSubsetError, GridValidationError
from processing.point_field import physical_range

VECTOR_SLICE_SCHEMA_VERSION = "s4.vector-slice/1.0"
VECTOR_SLICE_PRODUCT_TYPE = "vector_slice"


@dataclass(frozen=True)
class VectorSliceProduct:
    eastward: DepthSliceProduct
    northward: DepthSliceProduct
    #: sqrt(u² + v²) in the components' units, float64, NaN where missing.
    speed: np.ndarray
    #: A cell is missing when either component is missing there.
    missing_value_mask: np.ndarray
    speed_range: PhysicalRange
    schema_version: str = field(default=VECTOR_SLICE_SCHEMA_VERSION, init=False)
    product_type: str = field(default=VECTOR_SLICE_PRODUCT_TYPE, init=False)

    def __post_init__(self) -> None:
        for name in ("speed", "missing_value_mask"):
            object.__setattr__(self, name, _readonly_array(getattr(self, name)))

    @property
    def units(self) -> str:
        return self.eastward.variable_units


def build_vector_slice(eastward: DepthSliceProduct,
                       northward: DepthSliceProduct) -> VectorSliceProduct:
    """Pair two component slices; refuse any pair that is not cell-aligned."""
    east, north = eastward.data, northward.data
    if not (np.array_equal(east.longitude, north.longitude)
            and np.array_equal(east.latitude, north.latitude)):
        raise GridValidationError(
            "vector components are not on the same horizontal grid")
    if east.time_source_index != north.time_source_index:
        raise GridValidationError("vector components are at different times")
    if (eastward.interpolation.source_depth_indices
            != northward.interpolation.source_depth_indices):
        raise GridValidationError("vector components are at different depths")
    if eastward.variable_units != northward.variable_units:
        raise GridValidationError(
            f"vector components have different units: "
            f"{eastward.variable_units!r} and {northward.variable_units!r}")

    missing = np.asarray(east.missing_value_mask) | np.asarray(
        north.missing_value_mask)
    speed = np.hypot(np.asarray(east.values, dtype=np.float64),
                     np.asarray(north.values, dtype=np.float64))
    speed[missing] = np.nan
    speed_range = physical_range(speed, missing)
    if speed_range.valid_point_count == 0:
        raise AllMissingSubsetError(
            "every cell of the current-vector slice is missing a component")
    return VectorSliceProduct(eastward=eastward, northward=northward,
                              speed=speed, missing_value_mask=missing,
                              speed_range=speed_range)
