"""Benchmark conservative depth-slice reduction at model-grid scale.

Run from the repository root, for example::

    python -m processing.benchmark.slice_reduction \
        --shape 4251 4500 --budget 2000000 --land-fraction 0.35
"""

from __future__ import annotations

import argparse
import gc
import json
from statistics import median
from time import perf_counter

import numpy as np

from processing.depth_slice import (
    DepthInterpolationMetadata, DepthSliceData, DepthSliceDimensions,
    DepthSliceProduct,
)
from processing.domain import (
    CoordinateMetadata, CoordinateRoles, PhysicalRange, ProductIdentity,
    SpatialReference,
)
from processing.slice_reduction import reduce_depth_slice


def _product(rows: int, columns: int, land_fraction: float,
             seed: int) -> DepthSliceProduct:
    if rows < 1 or columns < 1:
        raise ValueError("shape dimensions must be positive")
    if not 0.0 <= land_fraction <= 1.0:
        raise ValueError("land_fraction must lie between zero and one")
    rng = np.random.default_rng(seed)
    values = rng.standard_normal((rows, columns), dtype=np.float32)
    missing = rng.random((rows, columns), dtype=np.float32) < land_fraction
    latitude = np.linspace(-80.0, 90.0, rows, dtype=np.float64)
    longitude = np.linspace(
        0.0, 360.0, columns, endpoint=False, dtype=np.float64)
    valid_count = int(values.size - np.count_nonzero(missing))
    return DepthSliceProduct(
        identity=ProductIdentity(
            dataset_id="benchmark-grid",
            dataset_version_id="benchmark-version",
            variable="water_temp",
            time_coordinate="time",
            time_value="2026-09-30T00:00:00Z",
        ),
        coordinates=CoordinateMetadata(
            names=CoordinateRoles(
                time="time", depth="depth", latitude="latitude",
                longitude="longitude"),
            dimensions={
                "time": "time", "depth": "depth", "latitude": "latitude",
                "longitude": "longitude",
            },
            units={
                "time": None, "depth": "m", "latitude": "degrees_north",
                "longitude": "degrees_east",
            },
            dtypes={
                "time": "datetime64[ns]", "depth": "float64",
                "latitude": "float64", "longitude": "float64",
            },
            time_encoding={"units": None, "calendar": None},
        ),
        spatial_reference=SpatialReference(
            crs="EPSG:4326", vertical_positive="down"),
        dimensions=DepthSliceDimensions(
            source_order=("time", "depth", "latitude", "longitude"),
            semantic_order=("latitude", "longitude"),
            slice_shape=(rows, columns),
        ),
        variable_units="degree_Celsius",
        source_dtype="float32",
        delivered_dtype="float32",
        provenance={"source": "synthetic benchmark"},
        interpolation=DepthInterpolationMetadata(
            policy="none",
            requested_depth=0.0,
            delivered_depth=0.0,
            source_depth_indices=(0,),
            source_depth_values=(0.0,),
            weights=(1.0,),
            is_interpolated=False,
        ),
        physical_range=PhysicalRange(
            minimum=None,
            maximum=None,
            valid_point_count=valid_count,
            missing_point_count=int(values.size - valid_count),
        ),
        data=DepthSliceData(
            longitude=longitude,
            latitude=latitude,
            values=values,
            missing_value_mask=missing,
            time_source_index=0,
            latitude_source_indices=tuple(range(rows)),
            longitude_source_indices=tuple(range(columns)),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shape", nargs=2, type=int, metavar=("ROWS", "COLUMNS"),
                        default=(4251, 4500))
    parser.add_argument("--budget", type=int, default=2_000_000)
    parser.add_argument("--land-fraction", type=float, default=0.35)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--target-ms", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=26067)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")

    rows, columns = args.shape
    product = _product(rows, columns, args.land_fraction, args.seed)
    # One warm-up removes import, dispatch and allocator cold-start effects.
    reduce_depth_slice(product, args.budget)
    samples: list[float] = []
    result = None
    for _ in range(args.repeats):
        gc.collect()
        started = perf_counter()
        result = reduce_depth_slice(product, args.budget)
        samples.append((perf_counter() - started) * 1000.0)
    assert result is not None and result.reduction is not None
    measured = median(samples)
    report = {
        "shape": [rows, columns],
        "source_cells": rows * columns,
        "budget": args.budget,
        "land_fraction": args.land_fraction,
        "factor": result.reduction.factor,
        "delivered_shape": list(result.dimensions.slice_shape),
        "delivered_cells": int(np.prod(result.dimensions.slice_shape)),
        "dtype": result.delivered_dtype,
        "cell_methods": result.reduction.cell_methods,
        "weighting": result.reduction.weighting,
        "samples_ms": [round(sample, 3) for sample in samples],
        "median_ms": round(measured, 3),
        "target_ms": args.target_ms,
        "target_met": measured < args.target_ms,
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
