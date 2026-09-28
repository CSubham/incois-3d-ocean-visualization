"""S3-to-S4 handoff for managed scalar model fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ingestion.query import (
    ModelFieldDescriptor, ModelFieldQuery, ModelFieldQueryError,
    ObservationQuery, ProfileIdentity, ProfileSearch, VariableUnavailable,
)
from processing.domain import (
    CoordinateRoles, DatasetIdentity, SamplingRequest, ScalarGridDescriptor,
    ScalarPointFieldProduct, ScalarSelection, SpatialReference,
)
from processing.depth_slice import (
    DepthSliceProduct, DepthSliceSelection, build_depth_slice,
)
from processing.errors import (
    InvalidRequestError, ManagedDataUnavailableError, VariableSelectionError,
)
from processing.execution import ProductBuilder, ProductRequest
from processing.observation import (
    ObservationMarkerProduct, ObservationProfileIdentity,
    ObservationProfileProduct, ObservationProfileSelection,
    ObservationRecordDescriptor, build_observation_markers_from_records,
    build_observation_profile_from_record,
)
from processing.point_field import prepare_sampled_scalar_point_field


def scalar_grid_descriptor(
        descriptor: ModelFieldDescriptor) -> ScalarGridDescriptor:
    """Map the S3 semantic descriptor onto the existing S4 contract."""
    return ScalarGridDescriptor(
        identity=DatasetIdentity(
            dataset_id=descriptor.dataset_id,
            dataset_version_id=descriptor.dataset_version_id,
        ),
        coordinates=CoordinateRoles(
            time=descriptor.time_coordinate,
            depth=descriptor.depth_coordinate,
            latitude=descriptor.latitude_coordinate,
            longitude=descriptor.longitude_coordinate,
        ),
        spatial_reference=SpatialReference(
            crs=descriptor.crs,
            vertical_positive=descriptor.vertical_positive,
        ),
        provenance=descriptor.provenance,
    )


def prepare_managed_scalar_point_field(
    query: ModelFieldQuery,
    dataset_version_id: str,
    selection: ScalarSelection,
    sampling: SamplingRequest,
    maximum_cells: int | None = None,
) -> ScalarPointFieldProduct:
    """Open one S3 field, run the existing S4 path, and always close it.

    S3 read failures become S4 failures a client can act on; their messages
    are already free of storage detail at the S3 boundary.
    """
    try:
        with query.open_model_field(
                dataset_version_id, selection.variable) as managed:
            return prepare_sampled_scalar_point_field(
                managed.dataset,
                scalar_grid_descriptor(managed.descriptor),
                selection,
                sampling,
                maximum_cells=maximum_cells,
            )
    except VariableUnavailable as exc:
        raise VariableSelectionError(str(exc)) from exc
    except ModelFieldQueryError as exc:
        raise ManagedDataUnavailableError(str(exc)) from exc


def managed_point_field_builder(query: ModelFieldQuery) -> ProductBuilder:
    """The product builder composition binds to the configured S3 reads."""
    def build(request: ProductRequest) -> ScalarPointFieldProduct:
        return prepare_managed_scalar_point_field(
            query, request.dataset_version_id, request.selection,
            request.sampling, maximum_cells=request.maximum_cells)

    return build


@dataclass(frozen=True)
class ManagedDepthSliceRequest:
    dataset_version_id: str
    selection: DepthSliceSelection
    maximum_cells: int | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.dataset_version_id, str)
                or not self.dataset_version_id.strip()):
            raise InvalidRequestError("a dataset_version_id is required")
        if self.maximum_cells is not None and self.maximum_cells < 1:
            raise InvalidRequestError("maximum_cells must be positive")


def prepare_managed_depth_slice(
        query: ModelFieldQuery,
        request: ManagedDepthSliceRequest) -> DepthSliceProduct:
    """Open one S3 model field and build a bounded depth slice."""
    try:
        with query.open_model_field(
                request.dataset_version_id,
                request.selection.variable) as managed:
            return build_depth_slice(
                managed.dataset,
                scalar_grid_descriptor(managed.descriptor),
                request.selection,
                maximum_cells=request.maximum_cells,
            )
    except VariableUnavailable as exc:
        raise VariableSelectionError(str(exc)) from exc
    except ModelFieldQueryError as exc:
        raise ManagedDataUnavailableError(str(exc)) from exc


def managed_depth_slice_builder(
        query: ModelFieldQuery,
        ) -> ProductBuilder[ManagedDepthSliceRequest, DepthSliceProduct]:
    """Bind depth-slice execution to the configured S3 model-field read."""
    def build(request: ManagedDepthSliceRequest) -> DepthSliceProduct:
        return prepare_managed_depth_slice(query, request)

    return build


@dataclass(frozen=True)
class ManagedObservationMarkerRequest:
    dataset_version_id: str
    search: ProfileSearch

    def __post_init__(self) -> None:
        if (not isinstance(self.dataset_version_id, str)
                or not self.dataset_version_id.strip()):
            raise InvalidRequestError(
                "an observation dataset_version_id is required")


@dataclass(frozen=True)
class ManagedObservationProfileRequest:
    identity: ProfileIdentity
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


def _record_descriptor(
        descriptors: Mapping[str, ObservationRecordDescriptor],
        dataset_version_id: str) -> ObservationRecordDescriptor:
    descriptor = descriptors.get(dataset_version_id)
    if descriptor is None:
        raise ManagedDataUnavailableError(
            f"dataset version {dataset_version_id!r} has no configured "
            "observation semantics")
    if descriptor.identity.dataset_version_id != dataset_version_id:
        raise InvalidRequestError(
            f"observation descriptor version "
            f"{descriptor.identity.dataset_version_id!r} contradicts "
            f"requested S3 version {dataset_version_id!r}")
    return descriptor


def prepare_managed_observation_markers(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor],
        request: ManagedObservationMarkerRequest) -> ObservationMarkerProduct:
    """Query S3 marker/profile records and build one S4 marker product."""
    descriptor = _record_descriptor(
        descriptors, request.dataset_version_id)
    try:
        marker_records = tuple(
            marker for marker in query.find_profile_markers(request.search)
            if marker.identity.dataset_version_id == request.dataset_version_id)
        records = tuple((marker, query.get_profile(marker.identity))
                        for marker in marker_records)
    except ModelFieldQueryError as exc:
        raise ManagedDataUnavailableError(str(exc)) from exc
    return build_observation_markers_from_records(records, descriptor)


def prepare_managed_observation_profile(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor],
        request: ManagedObservationProfileRequest) -> ObservationProfileProduct:
    """Query one exact S3 profile record and build its S4 product."""
    descriptor = _record_descriptor(
        descriptors, request.identity.dataset_version_id)
    try:
        profile = query.get_profile(request.identity)
    except ModelFieldQueryError as exc:
        raise ManagedDataUnavailableError(str(exc)) from exc
    return build_observation_profile_from_record(
        profile,
        descriptor,
        ObservationProfileSelection(
            identity=ObservationProfileIdentity(
                platform_id=request.identity.platform_id,
                cycle=request.identity.cycle,
            ),
            variables=request.variables,
        ),
    )


def managed_observation_marker_builder(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor],
        ) -> ProductBuilder[
            ManagedObservationMarkerRequest, ObservationMarkerProduct]:
    """Bind marker-product execution to one configured S3 query."""
    configured = dict(descriptors)

    def build(request: ManagedObservationMarkerRequest
              ) -> ObservationMarkerProduct:
        return prepare_managed_observation_markers(
            query, configured, request)

    return build


def managed_observation_profile_builder(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor],
        ) -> ProductBuilder[
            ManagedObservationProfileRequest, ObservationProfileProduct]:
    """Bind exact-profile execution to one configured S3 query."""
    configured = dict(descriptors)

    def build(request: ManagedObservationProfileRequest
              ) -> ObservationProfileProduct:
        return prepare_managed_observation_profile(
            query, configured, request)

    return build


__all__ = [
    "ManagedObservationMarkerRequest", "ManagedObservationProfileRequest",
    "ManagedDepthSliceRequest", "managed_depth_slice_builder",
    "managed_observation_marker_builder",
    "managed_observation_profile_builder", "managed_point_field_builder",
    "prepare_managed_observation_markers",
    "prepare_managed_observation_profile",
    "prepare_managed_scalar_point_field", "prepare_managed_depth_slice",
    "scalar_grid_descriptor",
]
