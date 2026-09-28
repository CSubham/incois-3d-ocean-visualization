"""Deterministic point-field products built only from selected source cells."""

from __future__ import annotations

import numpy as np

from processing.domain import (
    DimensionMetadata, PhysicalRange, PointFieldData, SamplingMetadata,
    SamplingRequest, ScalarGridDescriptor, ScalarPointFieldProduct,
    ScalarSelection, ScalarSubset, SourceCellIndex,
)
from processing.errors import AllMissingSubsetError
from processing.subsetter import subset_scalar_field


def _selected_flat_indices(point_count: int,
                           maximum_points: int) -> tuple[int, ...]:
    if maximum_points >= point_count:
        return tuple(range(point_count))
    if maximum_points == 1:
        return ((point_count - 1) // 2,)
    return tuple((position * (point_count - 1)) // (maximum_points - 1)
                 for position in range(maximum_points))


def physical_range(values: np.ndarray,
                   missing_mask: np.ndarray) -> PhysicalRange:
    flat_values = np.asarray(values).reshape(-1)
    flat_mask = np.asarray(missing_mask, dtype=bool).reshape(-1)
    valid = flat_values[~flat_mask]
    if valid.size == 0:
        minimum = maximum = None
    else:
        minimum = np.min(valid).item()
        maximum = np.max(valid).item()
    return PhysicalRange(
        minimum=minimum,
        maximum=maximum,
        valid_point_count=int(valid.size),
        missing_point_count=int(flat_mask.sum()),
    )


def build_sampled_scalar_point_field(
        subset: ScalarSubset,
        sampling: SamplingRequest) -> ScalarPointFieldProduct:
    """Build an auditable budget-limited product without inventing values."""
    full_range = physical_range(subset.values, subset.missing_value_mask)
    if full_range.valid_point_count == 0:
        raise AllMissingSubsetError(
            f"all {full_range.missing_point_count} selected cells of "
            f"{subset.identity.variable!r} are missing; there is no value to "
            "display")

    original_count = int(subset.values.size)
    selected_flat = _selected_flat_indices(
        original_count, sampling.maximum_points)
    selected_array = np.asarray(selected_flat, dtype=np.intp)
    depth_positions, latitude_positions, longitude_positions = \
        np.unravel_index(selected_array, subset.values.shape, order="C")

    delivered_values = subset.values[
        depth_positions, latitude_positions, longitude_positions]
    delivered_mask = subset.missing_value_mask[
        depth_positions, latitude_positions, longitude_positions]
    delivered_depth = subset.depth_values[depth_positions]
    delivered_latitude = subset.latitude_values[latitude_positions]
    delivered_longitude = subset.longitude_values[longitude_positions]

    source_indices = tuple(
        SourceCellIndex(
            time=subset.time_source_index,
            depth=subset.depth_source_indices[int(depth_position)],
            latitude=subset.latitude_source_indices[int(latitude_position)],
            longitude=subset.longitude_source_indices[int(longitude_position)],
        )
        for depth_position, latitude_position, longitude_position in zip(
            depth_positions, latitude_positions, longitude_positions)
    )
    delivered_count = len(selected_flat)
    omitted_count = original_count - delivered_count
    delivered_range = physical_range(delivered_values, delivered_mask)

    return ScalarPointFieldProduct(
        identity=subset.identity,
        coordinates=subset.coordinates,
        spatial_reference=subset.spatial_reference,
        dimensions=DimensionMetadata(
            source_order=subset.source_dimensions,
            semantic_order=subset.semantic_dimensions,
            subset_shape=tuple(int(size) for size in subset.values.shape),
        ),
        variable_units=subset.variable_units,
        source_dtype=str(subset.values.dtype),
        provenance=subset.provenance,
        sampling=SamplingMetadata(
            policy=sampling.policy,
            parameters={
                "basis": "index space: positions in the subset array, not "
                         "physical distance, so uneven depth levels are "
                         "sampled by level rather than by metre",
                "traversal": "C-order over (depth, latitude, longitude)",
                "multiple_points": "integer-even spacing including endpoints",
                "single_point": "lower central flat index",
                "masked_cells_eligible": True,
                "masked_cells_delivered": "with missing_value_mask true",
            },
            maximum_points=sampling.maximum_points,
            original_point_count=original_count,
            original_valid_point_count=full_range.valid_point_count,
            delivered_point_count=delivered_count,
            delivered_valid_point_count=delivered_range.valid_point_count,
            omitted_point_count=omitted_count,
            is_lossy=omitted_count > 0,
            selected_subset_flat_indices=selected_flat,
        ),
        full_subset_range=full_range,
        delivered_sample_range=delivered_range,
        points=PointFieldData(
            longitude=delivered_longitude,
            latitude=delivered_latitude,
            depth=delivered_depth,
            values=delivered_values,
            missing_value_mask=delivered_mask,
            source_indices=source_indices,
        ),
    )


def prepare_sampled_scalar_point_field(
        dataset,
        descriptor: ScalarGridDescriptor,
        selection: ScalarSelection,
        sampling: SamplingRequest,
        maximum_cells: int | None = None) -> ScalarPointFieldProduct:
    """Run the pure in-memory subset-and-build path."""
    subset = subset_scalar_field(dataset, descriptor, selection, maximum_cells)
    return build_sampled_scalar_point_field(subset, sampling)
