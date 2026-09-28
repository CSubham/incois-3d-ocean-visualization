"""Pure S4 scientific processing contracts and scalar point-field path."""

from processing.domain import (
    IDENTITY_TRANSFORM, MISSING_VALUE_MASK, PRODUCT_SCHEMA_VERSION,
    PRODUCT_TYPE, SAMPLING_POLICY, VERTICAL_POSITIVE,
    CoordinateMetadata, CoordinateRoles, CoordinateTransform,
    DatasetIdentity, DepthBounds, DimensionMetadata, GeographicBounds,
    MaskSemantics, PhysicalRange, PointFieldData, ProductIdentity,
    SamplingMetadata, SamplingRequest, ScalarGridDescriptor,
    ScalarPointFieldProduct, ScalarSelection, ScalarSubset, SourceCellIndex,
    SpatialReference,
)
from processing.errors import (
    AllMissingSubsetError, EmptySubsetError, GridValidationError,
    InvalidRequestError, PointBudgetError, ProcessingError,
    TimeSelectionError, VariableSelectionError,
)
from processing.point_field import (
    build_sampled_scalar_point_field, prepare_sampled_scalar_point_field,
)
from processing.subsetter import subset_scalar_field

__all__ = [
    "IDENTITY_TRANSFORM", "MISSING_VALUE_MASK", "PRODUCT_SCHEMA_VERSION",
    "PRODUCT_TYPE", "SAMPLING_POLICY", "VERTICAL_POSITIVE",
    "AllMissingSubsetError", "CoordinateMetadata", "CoordinateRoles",
    "CoordinateTransform", "DatasetIdentity", "DepthBounds",
    "DimensionMetadata", "EmptySubsetError", "GeographicBounds",
    "GridValidationError", "InvalidRequestError", "MaskSemantics",
    "PhysicalRange", "PointBudgetError", "PointFieldData",
    "ProcessingError", "ProductIdentity", "SamplingMetadata",
    "SamplingRequest", "ScalarGridDescriptor", "ScalarPointFieldProduct",
    "ScalarSelection", "ScalarSubset", "SourceCellIndex",
    "SpatialReference", "TimeSelectionError", "VariableSelectionError",
    "build_sampled_scalar_point_field", "prepare_sampled_scalar_point_field",
    "subset_scalar_field",
]
