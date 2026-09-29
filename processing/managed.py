"""S3-to-S4 handoff for managed scalar model fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ingestion.query import (
    ModelFieldDescriptor, ModelFieldQuery, ModelFieldQueryError,
    ObservationQuery, ObservationVersionDescriptor, ProfileIdentity,
    ProfileNotFound, ProfileSearch, VariableUnavailable,
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
    ObservationIdentityError, WorkLimitError,
)
from processing.execution import ProductBuilder, ProductRequest
from processing.observation import (
    ObservationMarkerProduct, ObservationProfileIdentity,
    ObservationProfileProduct, ObservationProfileSelection,
    ObservationRecordDescriptor, build_observation_markers_from_records,
    build_observation_profile_from_record,
)
from processing.point_field import prepare_sampled_scalar_point_field
from processing.slice_reduction import reduce_depth_slice
from processing.vector_slice import VectorSliceProduct, build_vector_slice


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
    #: Work ceiling: source cells this server reads for one slice.
    maximum_cells: int | None = None
    #: View budget: cells delivered; a larger slice is reduced by a recorded
    #: block mean (processing.slice_reduction). None delivers source cells.
    display_cells: int | None = None
    #: Longest delivered side, e.g. the renderer's texture limit.
    display_side: int | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.dataset_version_id, str)
                or not self.dataset_version_id.strip()):
            raise InvalidRequestError("a dataset_version_id is required")
        for name in ("maximum_cells", "display_cells", "display_side"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise InvalidRequestError(f"{name} must be positive")


def prepare_managed_depth_slice(
        query: ModelFieldQuery,
        request: ManagedDepthSliceRequest) -> DepthSliceProduct:
    """Open one S3 model field and build a bounded depth slice."""
    try:
        with query.open_model_field(
                request.dataset_version_id,
                request.selection.variable) as managed:
            product = build_depth_slice(
                managed.dataset,
                scalar_grid_descriptor(managed.descriptor),
                request.selection,
                maximum_cells=request.maximum_cells,
            )
        if request.display_cells is None:
            return product
        return reduce_depth_slice(product, request.display_cells,
                                  request.display_side)
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
class ManagedVectorSliceRequest:
    """Both components of one current vector, sliced the same way."""

    dataset_version_id: str
    eastward: DepthSliceSelection
    northward: DepthSliceSelection
    maximum_cells: int | None = None
    display_cells: int | None = None
    display_side: int | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.dataset_version_id, str)
                or not self.dataset_version_id.strip()):
            raise InvalidRequestError("a dataset_version_id is required")
        if (self.eastward.time != self.northward.time
                or self.eastward.area != self.northward.area
                or self.eastward.depth != self.northward.depth
                or self.eastward.interpolation != self.northward.interpolation):
            raise InvalidRequestError(
                "both vector components need the same time, area and depth")
        if self.eastward.variable == self.northward.variable:
            raise InvalidRequestError(
                "the eastward and northward components must differ")
        for name in ("maximum_cells", "display_cells", "display_side"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise InvalidRequestError(f"{name} must be positive")


def prepare_managed_vector_slice(
        query: ModelFieldQuery,
        request: ManagedVectorSliceRequest) -> VectorSliceProduct:
    """Slice each component through the scalar path, then pair them."""
    def component(selection: DepthSliceSelection) -> DepthSliceProduct:
        return prepare_managed_depth_slice(query, ManagedDepthSliceRequest(
            request.dataset_version_id,
            selection,
            maximum_cells=request.maximum_cells,
            display_cells=request.display_cells,
            display_side=request.display_side,
        ))

    return build_vector_slice(component(request.eastward),
                              component(request.northward))


def managed_vector_slice_builder(
        query: ModelFieldQuery,
        ) -> ProductBuilder[ManagedVectorSliceRequest, VectorSliceProduct]:
    """Bind current-vector slices to the configured S3 model-field read."""
    def build(request: ManagedVectorSliceRequest) -> VectorSliceProduct:
        return prepare_managed_vector_slice(query, request)

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


def observation_record_descriptor(
        descriptor: ObservationVersionDescriptor) -> ObservationRecordDescriptor:
    """Map what S3 declares about an observation version onto S4's contract."""
    return ObservationRecordDescriptor(
        identity=DatasetIdentity(
            dataset_id=descriptor.dataset_id,
            dataset_version_id=descriptor.dataset_version_id,
        ),
        spatial_reference=SpatialReference(
            crs=descriptor.crs,
            vertical_positive=descriptor.vertical_positive,
        ),
        vertical_kind=descriptor.vertical_kind,
        vertical_coordinate=descriptor.vertical_coordinate,
        vertical_units=descriptor.vertical_units,
        provenance=descriptor.provenance,
    )


def _record_descriptor(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor] | None,
        dataset_version_id: str) -> ObservationRecordDescriptor:
    """The version's semantics: an explicit override, else S3's declaration.

    Resolved per request, so versions imported after start-up are served.
    """
    if descriptors is not None:
        descriptor = descriptors.get(dataset_version_id)
        if descriptor is None:
            raise ManagedDataUnavailableError(
                f"dataset version {dataset_version_id!r} has no configured "
                "observation semantics")
    else:
        try:
            descriptor = observation_record_descriptor(
                query.describe_observation_version(dataset_version_id))
        except ModelFieldQueryError as exc:
            raise ManagedDataUnavailableError(str(exc)) from exc
    if descriptor.identity.dataset_version_id != dataset_version_id:
        raise InvalidRequestError(
            f"observation descriptor version "
            f"{descriptor.identity.dataset_version_id!r} contradicts "
            f"requested S3 version {dataset_version_id!r}")
    return descriptor


def prepare_managed_observation_markers(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor] | None,
        request: ManagedObservationMarkerRequest,
        maximum_markers: int | None = None) -> ObservationMarkerProduct:
    """Query S3 marker/profile records and build one S4 marker product.

    ``maximum_markers`` is checked before any profile record is read, so an
    over-wide search costs one index query rather than one read per profile.
    """
    descriptor = _record_descriptor(
        query, descriptors, request.dataset_version_id)
    try:
        marker_records = tuple(
            marker for marker in query.find_profile_markers(request.search)
            if marker.identity.dataset_version_id == request.dataset_version_id)
    except ModelFieldQueryError as exc:
        raise ManagedDataUnavailableError(str(exc)) from exc
    if maximum_markers is not None and len(marker_records) > maximum_markers:
        raise WorkLimitError(
            f"the search finds {len(marker_records)} profiles; this server "
            f"builds at most {maximum_markers} markers. Narrow the area or "
            "time window")
    try:
        records = tuple((marker, query.get_profile(marker.identity))
                        for marker in marker_records)
    except ModelFieldQueryError as exc:
        raise ManagedDataUnavailableError(str(exc)) from exc
    return build_observation_markers_from_records(records, descriptor)


def prepare_managed_observation_profile(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor] | None,
        request: ManagedObservationProfileRequest) -> ObservationProfileProduct:
    """Query one exact S3 profile record and build its S4 product."""
    descriptor = _record_descriptor(
        query, descriptors, request.identity.dataset_version_id)
    try:
        profile = query.get_profile(request.identity)
    except ProfileNotFound as exc:
        raise ObservationIdentityError(str(exc)) from exc
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
        descriptors: Mapping[str, ObservationRecordDescriptor] | None = None,
        maximum_markers: int | None = None,
        ) -> ProductBuilder[
            ManagedObservationMarkerRequest, ObservationMarkerProduct]:
    """Bind marker-product execution to one configured S3 query.

    Without ``descriptors`` each version's semantics come from S3 per
    request; a mapping is an explicit override for fixtures.
    """
    configured = dict(descriptors) if descriptors is not None else None

    def build(request: ManagedObservationMarkerRequest
              ) -> ObservationMarkerProduct:
        return prepare_managed_observation_markers(
            query, configured, request, maximum_markers)

    return build


def managed_observation_profile_builder(
        query: ObservationQuery,
        descriptors: Mapping[str, ObservationRecordDescriptor] | None = None,
        ) -> ProductBuilder[
            ManagedObservationProfileRequest, ObservationProfileProduct]:
    """Bind exact-profile execution to one configured S3 query.

    Without ``descriptors`` each version's semantics come from S3 per request.
    """
    configured = dict(descriptors) if descriptors is not None else None

    def build(request: ManagedObservationProfileRequest
              ) -> ObservationProfileProduct:
        return prepare_managed_observation_profile(
            query, configured, request)

    return build


__all__ = [
    "observation_record_descriptor",
    "ManagedObservationMarkerRequest", "ManagedObservationProfileRequest",
    "ManagedDepthSliceRequest", "managed_depth_slice_builder",
    "ManagedVectorSliceRequest", "managed_vector_slice_builder",
    "prepare_managed_vector_slice",
    "managed_observation_marker_builder",
    "managed_observation_profile_builder", "managed_point_field_builder",
    "prepare_managed_observation_markers",
    "prepare_managed_observation_profile",
    "prepare_managed_scalar_point_field", "prepare_managed_depth_slice",
    "scalar_grid_descriptor",
]
