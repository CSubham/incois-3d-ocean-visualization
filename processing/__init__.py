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
    AllMissingObservationError, AllMissingSubsetError, EmptySubsetError,
    GridValidationError, InvalidRequestError, ManagedDataUnavailableError,
    ObservationIdentityError, ObservationValidationError,
    ObservationVariableError, PointBudgetError, ProcessingError,
    TimeSelectionError, UnknownRequestError, VariableSelectionError,
    WorkLimitError,
)
from processing.execution import (
    ExecutorCapabilities, Failure, JobState, LocalExecutor, ProductBuilder,
    ProductExecutor, ProductJob, ProductRequest, failure_for,
)
from processing.point_field import (
    build_sampled_scalar_point_field, prepare_sampled_scalar_point_field,
)
from processing.observation import (
    MARKER_PRODUCT_TYPE, MARKER_SCHEMA_VERSION, OBSERVATION_IDENTITY_TRANSFORM,
    OBSERVATION_MISSING_MASK, PROFILE_PRODUCT_TYPE, PROFILE_SCHEMA_VERSION,
    MarkerGroupingMetadata, ObservationCoordinateMetadata,
    ObservationCoordinateRoles, ObservationDatasetDescriptor,
    ObservationMarker, ObservationMarkerProduct, ObservationProfileIdentity,
    ObservationProfileProduct, ObservationProfileSelection,
    ObservationProfileVariable, ObservationVertical, ObservationVerticalRange,
    SkippedObservationProfile, build_observation_markers,
    build_observation_profile,
)
from processing.subsetter import subset_scalar_field

__all__ = [
    "IDENTITY_TRANSFORM", "MISSING_VALUE_MASK", "PRODUCT_SCHEMA_VERSION",
    "PRODUCT_TYPE", "SAMPLING_POLICY", "VERTICAL_POSITIVE",
    "AllMissingObservationError", "AllMissingSubsetError",
    "CoordinateMetadata", "CoordinateRoles",
    "CoordinateTransform", "DatasetIdentity", "DepthBounds",
    "DimensionMetadata", "EmptySubsetError", "GeographicBounds",
    "GridValidationError", "InvalidRequestError", "MaskSemantics",
    "PhysicalRange", "PointBudgetError", "PointFieldData",
    "ObservationIdentityError", "ObservationValidationError",
    "ObservationVariableError", "ProcessingError", "ProductIdentity",
    "SamplingMetadata",
    "SamplingRequest", "ScalarGridDescriptor", "ScalarPointFieldProduct",
    "ScalarSelection", "ScalarSubset", "SourceCellIndex",
    "SpatialReference", "TimeSelectionError", "VariableSelectionError",
    "ExecutorCapabilities", "Failure", "JobState", "LocalExecutor",
    "ManagedDataUnavailableError", "ProductBuilder", "ProductExecutor",
    "ProductJob", "ProductRequest", "UnknownRequestError", "WorkLimitError", "failure_for",
    "build_sampled_scalar_point_field", "prepare_sampled_scalar_point_field",
    "subset_scalar_field", "MARKER_PRODUCT_TYPE", "MARKER_SCHEMA_VERSION",
    "OBSERVATION_IDENTITY_TRANSFORM", "OBSERVATION_MISSING_MASK",
    "PROFILE_PRODUCT_TYPE", "PROFILE_SCHEMA_VERSION",
    "MarkerGroupingMetadata", "ObservationCoordinateMetadata",
    "ObservationCoordinateRoles", "ObservationDatasetDescriptor",
    "ObservationMarker", "ObservationMarkerProduct",
    "ObservationProfileIdentity", "ObservationProfileProduct",
    "ObservationProfileSelection", "ObservationProfileVariable",
    "ObservationVertical", "ObservationVerticalRange",
    "SkippedObservationProfile",
    "build_observation_markers", "build_observation_profile",
]
