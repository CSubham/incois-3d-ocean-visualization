"""Display reduction of horizontal slices to a view's cell budget.

A view cannot show more cells than it has pixels, so a slice larger than
the requested budget is reduced here, in S4, rather than dropped in the
browser. The reduction is a mask-aware block mean over square blocks of
source cells: missing cells (land) never contribute, and a block with no
valid cell stays missing, so coastlines do not bleed. The factor, method
and source shape are recorded on the product; a slice within budget is
delivered unchanged with factor 1.
"""

from __future__ import annotations

from dataclasses import replace
from math import ceil, sqrt

import numpy as np

from processing.depth_slice import (
    DepthSliceData, DepthSliceDimensions, DepthSliceProduct, SliceReduction,
)
from processing.errors import InvalidRequestError
from processing.point_field import physical_range

NO_REDUCTION = "none"
BLOCK_MEAN = "mask_aware_block_mean"


def reduction_factor(shape: tuple[int, int], maximum_cells: int,
                     maximum_side: int | None = None) -> int:
    """The smallest square block factor that fits the budget (and side limit)."""
    if maximum_cells < 1:
        raise InvalidRequestError("the cell budget must be positive")
    rows, columns = shape
    factor = max(1, ceil(sqrt(rows * columns / maximum_cells)))
    while ceil(rows / factor) * ceil(columns / factor) > maximum_cells:
        factor += 1
    if maximum_side is not None:
        while max(ceil(rows / factor), ceil(columns / factor)) > maximum_side:
            factor += 1
    return factor


def _block_mean(values: np.ndarray, missing: np.ndarray, factor: int
                ) -> tuple[np.ndarray, np.ndarray]:
    rows, columns = values.shape
    out_rows, out_columns = ceil(rows / factor), ceil(columns / factor)
    padded_rows, padded_columns = out_rows * factor, out_columns * factor
    valid = np.zeros((padded_rows, padded_columns), dtype=bool)
    valid[:rows, :columns] = ~missing
    total = np.zeros((padded_rows, padded_columns), dtype=np.float64)
    total[:rows, :columns] = np.where(missing, 0.0, values.astype(np.float64))
    shape = (out_rows, factor, out_columns, factor)
    sums = total.reshape(shape).sum(axis=(1, 3))
    counts = valid.reshape(shape).sum(axis=(1, 3))
    reduced_missing = counts == 0
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(reduced_missing, np.nan, sums / np.maximum(counts, 1))
    return means, reduced_missing


def _axis_centres(axis: np.ndarray, factor: int) -> np.ndarray:
    """Mean coordinate of each block, over the source cells it holds."""
    return np.array([axis[i:i + factor].astype(np.float64).mean()
                     for i in range(0, axis.size, factor)])


def reduce_depth_slice(product: DepthSliceProduct, maximum_cells: int,
                       maximum_side: int | None = None) -> DepthSliceProduct:
    """Fit a slice to a view's cell budget by a recorded block mean."""
    source_shape = product.dimensions.slice_shape
    factor = reduction_factor(source_shape, maximum_cells, maximum_side)
    if factor == 1:
        return replace(product, reduction=SliceReduction(
            NO_REDUCTION, 1, maximum_cells, source_shape, source_shape))

    data = product.data
    means, missing = _block_mean(np.asarray(data.values),
                                 np.asarray(data.missing_value_mask), factor)
    # Means are delivered in float64 unless the source was already wider.
    delivered = means.astype(np.result_type(data.values.dtype, np.float32))
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
        reduction=SliceReduction(BLOCK_MEAN, factor, maximum_cells,
                                 source_shape, shape),
    )
    return reduced
