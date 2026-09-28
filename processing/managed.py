"""S3-to-S4 handoff for managed scalar model fields."""

from __future__ import annotations

from ingestion.query import (
    ModelFieldDescriptor, ModelFieldQuery, ModelFieldQueryError,
    VariableUnavailable,
)
from processing.domain import (
    CoordinateRoles, DatasetIdentity, SamplingRequest, ScalarGridDescriptor,
    ScalarPointFieldProduct, ScalarSelection, SpatialReference,
)
from processing.errors import (
    ManagedDataUnavailableError, VariableSelectionError,
)
from processing.execution import ProductBuilder, ProductRequest
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


__all__ = ["managed_point_field_builder", "prepare_managed_scalar_point_field",
           "scalar_grid_descriptor"]
