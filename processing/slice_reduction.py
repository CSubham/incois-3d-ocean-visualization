"""Display reduction of horizontal slices to a view's cell budget.

A view cannot show more cells than it has pixels, so a slice larger than
the requested budget is reduced here, in S4, rather than dropped in the
browser. The reduction is a mask-aware, cell-area-weighted block mean over
square blocks of a regular latitude/longitude grid. Missing cells (land)
carry zero weight, and a block with no valid cell stays missing, so coastlines
do not bleed. The factor, method, weighting and source shape are recorded on
the product; a slice within budget is delivered unchanged with factor 1.
"""

from __future__ import annotations

from dataclasses import replace
from math import ceil, sqrt

import numpy as np

from processing.depth_slice import (
    DepthSliceData, DepthSliceDimensions, DepthSliceProduct, SliceReduction,
)
from processing.errors import GridValidationError, InvalidRequestError
from processing.point_field import physical_range

NO_REDUCTION = "none"
BLOCK_MEAN = "mask_aware_block_mean"
CELL_METHODS = "area: mean"
AREA_WEIGHTING = "cos(latitude) cell-area weights on a regular lat/lon grid"

_LATITUDE_UNITS = {
    "degree_north", "degree_n", "degrees_north", "degrees_n", "degreen",
    "degreesn",
}
_LONGITUDE_UNITS = {
    "degree_east", "degree_e", "degrees_east", "degrees_e", "degreee",
    "degreese",
}


def reduction_factor(shape: tuple[int, int], maximum_cells: int,
                     maximum_side: int | None = None) -> int:
    """The smallest square block factor that fits the budget (and side limit)."""
    if (isinstance(maximum_cells, bool)
            or not isinstance(maximum_cells, int)
            or maximum_cells < 1):
        raise InvalidRequestError("the cell budget must be positive")
    rows, columns = shape
    if rows < 1 or columns < 1:
        raise InvalidRequestError("the source slice shape must be non-empty")
    if (maximum_side is not None
            and (isinstance(maximum_side, bool)
                 or not isinstance(maximum_side, int)
                 or maximum_side < 1)):
        raise InvalidRequestError("the maximum delivered side must be positive")
    factor = max(1, ceil(sqrt(rows * columns / maximum_cells)))
    while ceil(rows / factor) * ceil(columns / factor) > maximum_cells:
        factor += 1
    if maximum_side is not None:
        while max(ceil(rows / factor), ceil(columns / factor)) > maximum_side:
            factor += 1
    return factor


#: How far a coordinate may sit from its place on the ideal regular axis,
#: as a fraction of one cell. Sources store axes rounded (HYCOM longitude to
#: about 1e-4 degrees, latitude to float32), so neighbouring steps differ
#: slightly; cell areas are what matter here, and 1% of a cell is far below
#: any effect on an area weight.
POSITION_TOLERANCE = 0.01


def _regular_axis(axis: np.ndarray, name: str) -> np.ndarray:
    values = np.asarray(axis, dtype=np.float64)
    if values.ndim != 1 or not bool(np.isfinite(values).all()):
        raise GridValidationError(f"{name} must be a finite coordinate vector")
    if values.size < 2:
        return values
    step = (values[-1] - values[0]) / (values.size - 1)
    ideal = values[0] + step * np.arange(values.size)
    if step == 0.0 or bool(
            (np.abs(values - ideal) > abs(step) * POSITION_TOLERANCE).any()):
        raise GridValidationError(
            f"area-weighted slice reduction requires regular {name} spacing")
    return values


def _normalised_unit(unit: str | None) -> str:
    return "" if unit is None else unit.strip().lower().replace(" ", "_")


def _latitude_weights(product: DepthSliceProduct) -> np.ndarray:
    units = product.coordinates.units
    if _normalised_unit(units.get("latitude")) not in _LATITUDE_UNITS:
        raise GridValidationError(
            "area-weighted slice reduction requires latitude in degrees north")
    if _normalised_unit(units.get("longitude")) not in _LONGITUDE_UNITS:
        raise GridValidationError(
            "area-weighted slice reduction requires longitude in degrees east")
    latitude = _regular_axis(product.data.latitude, "latitude")
    _regular_axis(product.data.longitude, "longitude")
    if bool(((latitude < -90.0) | (latitude > 90.0)).any()):
        raise GridValidationError(
            "latitude values must lie between -90 and 90 degrees")
    return np.cos(np.deg2rad(latitude))


def _block_mean(values: np.ndarray, missing: np.ndarray,
                latitude_weights: np.ndarray, factor: int
                ) -> tuple[np.ndarray, np.ndarray]:
    """Area-weight blocks using bounded, delivered-precision accumulators.

    Each source row has one cosine-latitude weight. Contiguous, bounded groups
    of block rows are reduced across longitude and then latitude. No padded
    grid or source-sized floating-point value/weight copy is materialized.
    """
    rows, columns = values.shape
    out_rows, out_columns = ceil(rows / factor), ceil(columns / factor)
    delivered_dtype = np.result_type(values.dtype, np.float32)
    accumulator_dtype = np.dtype(delivered_dtype)
    weights = latitude_weights.astype(accumulator_dtype, copy=False)
    sums = np.empty((out_rows, out_columns), dtype=accumulator_dtype)
    weight_sums = np.empty((out_rows, out_columns), dtype=accumulator_dtype)
    full_columns = columns // factor * factor
    full_out_columns = full_columns // factor
    full_rows = rows // factor * factor
    output_row_chunk = 256
    def accumulate(source_start: int, source_end: int, output_start: int,
                   output_count: int, rows_per_block: int) -> None:
        source_values = values[source_start:source_end]
        source_missing = missing[source_start:source_end]
        block_weights = weights[source_start:source_end].reshape(
            output_count, rows_per_block)
        if full_columns:
            block_values = source_values[:, :full_columns].reshape(
                output_count, rows_per_block, full_out_columns, factor)
            valid = ~source_missing[:, :full_columns].reshape(
                output_count, rows_per_block, full_out_columns, factor)
            masked_values = np.where(valid, block_values, 0)
            row_totals = np.sum(
                masked_values, axis=3, dtype=accumulator_dtype)
            row_totals *= block_weights[:, :, None]
            np.sum(
                row_totals, axis=1, dtype=accumulator_dtype,
                out=sums[output_start:output_start + output_count,
                         :full_out_columns])
            np.sum(valid, axis=3, dtype=accumulator_dtype, out=row_totals)
            row_totals *= block_weights[:, :, None]
            np.sum(
                row_totals, axis=1, dtype=accumulator_dtype,
                out=weight_sums[
                    output_start:output_start + output_count,
                    :full_out_columns])

        if full_columns < columns:
            edge_values = source_values[:, full_columns:]
            edge_valid = ~source_missing[:, full_columns:]
            row_totals = np.sum(
                edge_values, axis=1, dtype=accumulator_dtype, where=edge_valid,
                initial=0.0).reshape(output_count, rows_per_block)
            row_totals *= block_weights
            np.sum(
                row_totals, axis=1, dtype=accumulator_dtype,
                out=sums[output_start:output_start + output_count, -1])
            np.sum(
                edge_valid, axis=1, dtype=accumulator_dtype,
                out=row_totals.reshape(-1))
            row_totals *= block_weights
            np.sum(
                row_totals, axis=1, dtype=accumulator_dtype,
                out=weight_sums[
                    output_start:output_start + output_count, -1])

    full_output_rows = full_rows // factor
    for output_start in range(0, full_output_rows, output_row_chunk):
        output_count = min(
            output_row_chunk, full_output_rows - output_start)
        source_start = output_start * factor
        source_end = source_start + output_count * factor
        accumulate(source_start, source_end, output_start,
                   output_count, factor)

    if full_rows < rows:
        accumulate(full_rows, rows, full_output_rows, 1, rows - full_rows)

    reduced_missing = weight_sums == 0.0
    means = np.full((out_rows, out_columns), np.nan, dtype=delivered_dtype)
    np.divide(sums, weight_sums, out=means, where=~reduced_missing)
    return means, reduced_missing


def _axis_centres(axis: np.ndarray, factor: int) -> np.ndarray:
    """Mean coordinate of each block, over the source cells it holds."""
    values = np.asarray(axis, dtype=np.float64)
    starts = np.arange(0, values.size, factor)
    counts = np.minimum(factor, values.size - starts)
    return np.add.reduceat(values, starts) / counts


def reduce_depth_slice(product: DepthSliceProduct, maximum_cells: int,
                       maximum_side: int | None = None) -> DepthSliceProduct:
    """Fit a slice to a view's cell budget by a recorded block mean."""
    source_shape = product.dimensions.slice_shape
    factor = reduction_factor(source_shape, maximum_cells, maximum_side)
    if factor == 1:
        return replace(product, reduction=SliceReduction(
            method=NO_REDUCTION,
            factor=1,
            maximum_cells=maximum_cells,
            source_shape=source_shape,
            delivered_shape=source_shape,
        ))

    data = product.data
    delivered, missing = _block_mean(
        np.asarray(data.values),
        np.asarray(data.missing_value_mask),
        _latitude_weights(product),
        factor,
    )
    shape = (int(delivered.shape[0]), int(delivered.shape[1]))
    reduced = replace(
        product,
        dimensions=DepthSliceDimensions(
            source_order=product.dimensions.source_order,
            semantic_order=product.dimensions.semantic_order,
            slice_shape=shape),
        delivered_dtype=str(delivered.dtype),
        physical_range=physical_range(delivered, missing),
        data=DepthSliceData(
            longitude=_axis_centres(np.asarray(data.longitude), factor),
            latitude=_axis_centres(np.asarray(data.latitude), factor),
            values=delivered,
            missing_value_mask=missing,
            time_source_index=data.time_source_index,
            latitude_source_indices=data.latitude_source_indices[::factor],
            longitude_source_indices=data.longitude_source_indices[::factor],
        ),
        reduction=SliceReduction(
            method=BLOCK_MEAN,
            factor=factor,
            maximum_cells=maximum_cells,
            source_shape=source_shape,
            delivered_shape=shape,
            cell_methods=CELL_METHODS,
            weighting=AREA_WEIGHTING,
        ),
    )
    return reduced
