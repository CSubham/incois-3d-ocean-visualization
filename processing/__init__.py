"""Pure S4 scientific processing contracts and scalar point-field path."""

from processing.domain import (
    PRODUCT_SCHEMA_VERSION, PRODUCT_TYPE, SAMPLING_POLICY,
    CoordinateMetadata, CoordinateRoles, DatasetIdentity, DepthBounds,
    DimensionMetadata, GeographicBounds, PhysicalRange, PointFieldData,
    ProductIdentity, SamplingMetadata, SamplingRequest, ScalarGridDescriptor,
    ScalarPointFieldProduct, ScalarSelection, ScalarSubset, SourceCellIndex,
)
from processing.errors import (
    EmptySubsetError, GridValidationError, InvalidRequestError,
    PointBudgetError, ProcessingError, TimeSelectionError,
    VariableSelectionError,
)
from processing.point_field import (
    build_sampled_scalar_point_field, prepare_sampled_scalar_point_field,
)
from processing.subsetter import subset_scalar_field

__all__ = [
    "PRODUCT_SCHEMA_VERSION", "PRODUCT_TYPE", "SAMPLING_POLICY",
    "CoordinateMetadata", "CoordinateRoles", "DatasetIdentity",
    "DepthBounds", "DimensionMetadata", "EmptySubsetError",
    "GeographicBounds", "GridValidationError", "InvalidRequestError",
    "PhysicalRange", "PointBudgetError", "PointFieldData",
    "ProcessingError", "ProductIdentity", "SamplingMetadata",
    "SamplingRequest", "ScalarGridDescriptor", "ScalarPointFieldProduct",
    "ScalarSelection", "ScalarSubset", "SourceCellIndex",
    "TimeSelectionError", "VariableSelectionError",
    "build_sampled_scalar_point_field", "prepare_sampled_scalar_point_field",
    "subset_scalar_field",
]
