"""Alignment and conservative display reduction of current-vector slices."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import xarray as xr

from ingestion.query import VariableSummary
from ingestion.query_memory import InMemoryModelFieldQuery
from ingestion.tests.query_support import MODEL_VERSION_ID, in_memory_case
from processing import (
    DepthSliceSelection, GeographicBounds, GridValidationError,
    build_depth_slice, build_vector_slice,
)
from processing.managed import (
    ManagedVectorSliceRequest, prepare_managed_vector_slice,
)
from processing.slice_reduction import BLOCK_MEAN, reduce_depth_slice
from processing.tests import fixtures


def _component(
    variable: str,
    values: np.ndarray,
    *,
    latitudes: np.ndarray | None = None,
    longitudes: np.ndarray | None = None,
    version: str = fixtures.VERSION,
):
    rows, columns = values.shape
    latitudes = (np.arange(rows, dtype=np.float64)
                 if latitudes is None else latitudes)
    longitudes = (np.arange(columns, dtype=np.float64) + 60.0
                  if longitudes is None else longitudes)
    dataset = xr.Dataset(
        {variable: (
            ("time", "depth", "lat", "lon"),
            values.reshape(1, 1, rows, columns),
            {"units": "m/s"},
        )},
        coords={
            "time": np.array(["2026-01-01"], dtype="datetime64[ns]"),
            "depth": ("depth", [0.0], {"units": "m", "positive": "down"}),
            "lat": ("lat", latitudes, {"units": "degrees_north"}),
            "lon": ("lon", longitudes, {"units": "degrees_east"}),
        },
    )
    return build_depth_slice(
        dataset,
        fixtures.descriptor(version),
        DepthSliceSelection(
            variable=variable,
            time=dataset.time.values[0],
            area=GeographicBounds(
                west=float(longitudes[0]), east=float(longitudes[-1]),
                south=float(latitudes[0]), north=float(latitudes[-1]),
            ),
            depth=0.0,
        ),
    )


def _query_with_currents() -> InMemoryModelFieldQuery:
    query = in_memory_case().query
    assert isinstance(query, InMemoryModelFieldQuery)
    version = query._versions[MODEL_VERSION_ID]
    dataset = version.dataset.copy()
    shape = dataset["water_temp"].shape
    eastward = np.broadcast_to(
        np.array([1.0, -1.0, 1.0, -1.0], dtype=np.float32), shape,
    ).copy()
    northward = np.zeros(shape, dtype=np.float32)
    dims = dataset["water_temp"].dims
    dataset["water_u"] = (dims, eastward, {"units": "m/s"})
    dataset["water_v"] = (dims, northward, {"units": "m/s"})
    base = version.descriptors["water_temp"]
    descriptors = {
        **version.descriptors,
        "water_u": replace(base, variable="water_u", units="m/s"),
        "water_v": replace(base, variable="water_v", units="m/s"),
    }
    summary = replace(version.summary, variables=(
        *version.summary.variables,
        VariableSummary("water_u", "m/s"),
        VariableSummary("water_v", "m/s"),
    ))
    return InMemoryModelFieldQuery([
        replace(version, summary=summary, dataset=dataset,
                descriptors=descriptors),
    ])


def _selection(variable: str) -> DepthSliceSelection:
    return DepthSliceSelection(
        variable=variable,
        time=np.datetime64("2026-09-28T00:00:00", "ns"),
        area=GeographicBounds(west=72.0, east=75.0, south=8.0, north=9.0),
        depth=0.0,
    )


def test_managed_vector_reduces_components_before_deriving_speed():
    product = prepare_managed_vector_slice(
        _query_with_currents(),
        ManagedVectorSliceRequest(
            dataset_version_id=MODEL_VERSION_ID,
            eastward=_selection("water_u"),
            northward=_selection("water_v"),
            maximum_cells=100,
            display_cells=2,
        ),
    )

    assert product.eastward.dimensions.slice_shape == (1, 2)
    assert product.eastward.reduction.method == BLOCK_MEAN
    assert product.eastward.reduction.factor == 2
    assert product.northward.reduction == product.eastward.reduction
    np.testing.assert_allclose(product.eastward.data.values, 0.0, atol=1e-7)
    np.testing.assert_allclose(product.speed, 0.0, atol=1e-7)
    assert product.eastward.data.latitude_source_indices == (0,)
    assert product.eastward.data.longitude_source_indices == (0, 2)


@pytest.mark.parametrize("field", ["dataset_id", "dataset_version_id"])
def test_vector_alignment_rejects_different_dataset_identity(field):
    eastward = _component("water_u", np.ones((2, 3), dtype=np.float32))
    northward = _component("water_v", np.ones((2, 3), dtype=np.float32))
    changed = replace(
        northward.identity,
        **{field: f"different-{field}"},
    )

    with pytest.raises(GridValidationError, match="dataset versions"):
        build_vector_slice(eastward, replace(northward, identity=changed))


def test_vector_alignment_rejects_different_horizontal_source_indices():
    eastward = _component("water_u", np.ones((2, 3), dtype=np.float32))
    northward = _component("water_v", np.ones((2, 3), dtype=np.float32))
    changed = replace(
        northward.data,
        longitude_source_indices=(0, 1, 7),
    )

    with pytest.raises(GridValidationError, match="horizontal source cells"):
        build_vector_slice(eastward, replace(northward, data=changed))


def test_hycom_style_rounded_axes_reduce_as_a_regular_vector_grid():
    longitudes = np.array([
        30.0, 30.0799560546875, 30.1600341796875,
        30.239990234375, 30.3199462890625,
    ])
    latitudes = (np.float32(-30.0)
                 + np.float32(0.04) * np.arange(9, dtype=np.float32))
    eastward = _component(
        "water_u", np.ones((9, 5), dtype=np.float32),
        latitudes=latitudes, longitudes=longitudes,
    )
    northward = _component(
        "water_v", np.full((9, 5), 2.0, dtype=np.float32),
        latitudes=latitudes, longitudes=longitudes,
    )

    product = build_vector_slice(
        reduce_depth_slice(eastward, maximum_cells=6),
        reduce_depth_slice(northward, maximum_cells=6),
    )

    assert product.eastward.reduction.factor == 3
    assert product.eastward.dimensions.slice_shape == (3, 2)
    np.testing.assert_allclose(product.speed, np.sqrt(5.0), rtol=1e-6)
