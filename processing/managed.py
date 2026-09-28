"""S3-to-S4 handoff for managed scalar model fields."""

from __future__ import annotations

from ingestion.query import ModelFieldDescriptor, ModelFieldQuery
from processing.domain import (
    CoordinateRoles, DatasetIdentity, SamplingRequest, ScalarGridDescriptor,
    ScalarPointFieldProduct, ScalarSelection, SpatialReference,
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
) -> ScalarPointFieldProduct:
    """Open one S3 field, run the existing S4 path, and always close it."""
    with query.open_model_field(
            dataset_version_id, selection.variable) as managed:
        return prepare_sampled_scalar_point_field(
            managed.dataset,
            scalar_grid_descriptor(managed.descriptor),
            selection,
            sampling,
        )


__all__ = ["prepare_managed_scalar_point_field", "scalar_grid_descriptor"]
