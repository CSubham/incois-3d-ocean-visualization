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
    AllMissingObservationError, AllMissingSubsetError, DepthSelectionError,
    EmptySubsetError, GridValidationError, InvalidRequestError,
    ManagedDataUnavailableError, ObservationIdentityError,
    ObservationValidationError,
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
from processing.depth_slice import (
    DEPTH_POLICIES, EXACT_DEPTH_POLICY, LINEAR_DEPTH_POLICY,
    SLICE_PRODUCT_TYPE, SLICE_SCHEMA_VERSION, DepthInterpolationMetadata,
    DepthSliceData, DepthSliceDimensions, DepthSliceProduct,
    DepthSliceSelection, build_depth_slice,
)
from processing.observation import (
    MARKER_PRODUCT_TYPE, MARKER_SCHEMA_VERSION, OBSERVATION_IDENTITY_TRANSFORM,
    OBSERVATION_MISSING_MASK, OBSERVATION_RECORD_MISSING_MASK,
    OBSERVATION_RECORD_TRANSFORM, PROFILE_PRODUCT_TYPE,
    PROFILE_SCHEMA_VERSION,
    MarkerGroupingMetadata, ObservationCoordinateMetadata,
    ObservationCoordinateRoles, ObservationDatasetDescriptor,
    ObservationMarker, ObservationMarkerProduct, ObservationProfileIdentity,
    ObservationProfileProduct, ObservationProfileSelection,
    ObservationProfileVariable, ObservationRecordDescriptor,
    ObservationVertical,
    ObservationVerticalRange, SkippedObservationProfile,
    build_observation_markers, build_observation_markers_from_records,
    build_observation_profile, build_observation_profile_from_record,
)
from processing.subsetter import subset_scalar_field

__all__ = [
    "IDENTITY_TRANSFORM", "MISSING_VALUE_MASK", "PRODUCT_SCHEMA_VERSION",
    "PRODUCT_TYPE", "SAMPLING_POLICY", "VERTICAL_POSITIVE",
    "AllMissingObservationError", "AllMissingSubsetError",
    "DepthSelectionError",
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
    "DEPTH_POLICIES", "EXACT_DEPTH_POLICY", "LINEAR_DEPTH_POLICY",
    "SLICE_PRODUCT_TYPE", "SLICE_SCHEMA_VERSION",
    "DepthInterpolationMetadata", "DepthSliceData", "DepthSliceDimensions",
    "DepthSliceProduct", "DepthSliceSelection", "build_depth_slice",
    "subset_scalar_field", "MARKER_PRODUCT_TYPE", "MARKER_SCHEMA_VERSION",
    "OBSERVATION_IDENTITY_TRANSFORM", "OBSERVATION_MISSING_MASK",
    "OBSERVATION_RECORD_MISSING_MASK", "OBSERVATION_RECORD_TRANSFORM",
    "PROFILE_PRODUCT_TYPE", "PROFILE_SCHEMA_VERSION",
    "MarkerGroupingMetadata", "ObservationCoordinateMetadata",
    "ObservationCoordinateRoles", "ObservationDatasetDescriptor",
    "ObservationMarker", "ObservationMarkerProduct",
    "ObservationProfileIdentity", "ObservationProfileProduct",
    "ObservationProfileSelection", "ObservationProfileVariable",
    "ObservationRecordDescriptor",
    "ObservationVertical", "ObservationVerticalRange",
    "SkippedObservationProfile",
    "build_observation_markers", "build_observation_markers_from_records",
    "build_observation_profile", "build_observation_profile_from_record",
]
