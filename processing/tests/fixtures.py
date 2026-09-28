"""A small decoded grid and a stand-in for the storage-bound product builder."""

from __future__ import annotations

from typing import Mapping

import numpy as np
import xarray as xr

from processing import (
    CoordinateRoles, DatasetIdentity, DepthBounds, GeographicBounds,
    ManagedDataUnavailableError, ProductBuilder, ProductRequest,
    SamplingRequest, ScalarGridDescriptor, ScalarSelection, SpatialReference,
    prepare_sampled_scalar_point_field,
)

VERSION = "import-123"


def grid() -> xr.Dataset:
    shape = (2, 3, 3, 4)
    temperature = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    return xr.Dataset(
        data_vars={"water_temp": (("time", "depth", "lat", "lon"), temperature,
                                  {"units": "degree_Celsius"})},
        coords={
            "time": np.array(["2026-01-01", "2026-01-02"],
                             dtype="datetime64[ns]"),
            "depth": ("depth", [0.0, 10.0, 20.0],
                      {"units": "m", "positive": "down"}),
            "lat": ("lat", [-10.0, 0.0, 10.0], {"units": "degrees_north"}),
            "lon": ("lon", [60.0, 70.0, 80.0, 90.0],
                    {"units": "degrees_east"}),
        },
    )


def descriptor(version: str = VERSION) -> ScalarGridDescriptor:
    return ScalarGridDescriptor(
        identity=DatasetIdentity(dataset_id="hycom-glby008",
                                 dataset_version_id=version),
        coordinates=CoordinateRoles(time="time", depth="depth",
                                    latitude="lat", longitude="lon"),
        spatial_reference=SpatialReference(crs="EPSG:4326",
                                           vertical_positive="down"),
        provenance={"source": "fixture://decoded-grid", "import_id": version},
    )


def request(maximum_points: int = 5, version: str = VERSION,
            variable: str = "water_temp") -> ProductRequest:
    return ProductRequest(
        dataset_version_id=version,
        selection=ScalarSelection(
            variable=variable,
            time=np.datetime64("2026-01-02T00:00:00", "ns"),
            area=GeographicBounds(west=65.0, east=90.0, south=-1.0, north=10.0),
            depth=DepthBounds(minimum=5.0, maximum=20.0),
        ),
        sampling=SamplingRequest(maximum_points=maximum_points),
    )


def builder(versions: Mapping[str, xr.Dataset] | None = None) -> ProductBuilder:
    """Stands in for the builder composition binds to the storage read path."""
    stored = dict(versions) if versions is not None else {VERSION: grid()}

    def build(product_request: ProductRequest):
        dataset = stored.get(product_request.dataset_version_id)
        if dataset is None:
            raise ManagedDataUnavailableError(
                f"dataset version {product_request.dataset_version_id!r} is "
                "not available")
        return prepare_sampled_scalar_point_field(
            dataset, descriptor(product_request.dataset_version_id),
            product_request.selection, product_request.sampling)

    return build
