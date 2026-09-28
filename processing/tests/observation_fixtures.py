"""Decoded Argo and glider-shaped datasets for S4 observation tests."""

from __future__ import annotations

import numpy as np
import xarray as xr

from processing import (
    DatasetIdentity, ObservationCoordinateRoles, ObservationDatasetDescriptor,
    ObservationProfileIdentity, ObservationProfileSelection,
    ObservationVertical,
)


ARGO_VERSION = "import-argo-1"
GLIDER_VERSION = "import-glider-1"


def argo() -> xr.Dataset:
    return xr.Dataset(
        data_vars={
            "TEMP": (
                ("observation",),
                np.array([20.1, np.nan, 18.4, 19.2, 17.0, 16.5, 15.8],
                         dtype=np.float32),
                {"units": "degree_Celsius"},
            ),
            "PSAL": (
                ("observation",),
                np.array([34.8, 34.9, 35.0, 34.7, 35.1, 35.2, 35.3],
                         dtype=np.float32),
                {"units": "1e-3"},
            ),
        },
        coords={
            "JULD": (
                "observation",
                np.array(["2026-01-01T00:00", "2026-01-01T00:01", "NaT",
                          "2026-01-01T00:03", "2026-01-02T00:00",
                          "2026-01-02T00:01", "2026-01-02T00:02"],
                         dtype="datetime64[ns]"),
            ),
            "LATITUDE": ("observation", np.array(
                [-4.0, -4.1, -4.2, -4.3, 7.0, 7.1, 7.2], dtype=np.float32),
                         {"units": "degrees_north"}),
            "LONGITUDE": ("observation", np.array(
                [70.0, 70.1, 70.2, 70.3, np.nan, 82.1, 82.2],
                dtype=np.float32), {"units": "degrees_east"}),
            "PRES": ("observation", np.array(
                [0.0, 20.0, np.nan, 10.0, 5.0, 50.0, 100.0],
                dtype=np.float32), {"units": "dbar"}),
            "PLATFORM_NUMBER": (
                "observation", np.array(
                    ["5901", "5901", "5901", "5901", "5902", "5902", "5902"],
                    dtype=object)),
            "CYCLE_NUMBER": (
                "observation", np.array(
                    ["7", "7", "7", "7", "8", "8", "8"], dtype=object)),
            "TEMP_QC": (
                "observation", np.array(
                    ["1", "4", None, "2", "1", "1", "3"], dtype=object)),
            "PSAL_QC": (
                "observation", np.array(
                    ["1", "1", "1", "2", "1", "1", "1"], dtype=object)),
        },
    )


def argo_descriptor() -> ObservationDatasetDescriptor:
    return ObservationDatasetDescriptor(
        identity=DatasetIdentity("Indian_ARGO_Floats", ARGO_VERSION),
        sample_dimension="observation",
        coordinates=ObservationCoordinateRoles(
            platform="PLATFORM_NUMBER", cycle="CYCLE_NUMBER",
            longitude="LONGITUDE", latitude="LATITUDE", time="JULD",
            vertical="PRES",
        ),
        vertical=ObservationVertical(kind="pressure", positive="down"),
        crs="EPSG:4326",
        qc_variables={"TEMP": "TEMP_QC", "PSAL": "PSAL_QC"},
        provenance={"import_id": ARGO_VERSION, "source": "INCOIS ERDDAP"},
    )


def argo_selection(*variables: str) -> ObservationProfileSelection:
    return ObservationProfileSelection(
        identity=ObservationProfileIdentity("5901", "7"),
        variables=tuple(variables) or ("TEMP", "PSAL"),
    )


def glider() -> xr.Dataset:
    return xr.Dataset(
        data_vars={
            "temperature": (
                ("row",), np.array([26.0, 24.5, np.nan, 21.0],
                                    dtype=np.float64),
                {"units": "degree_Celsius"},
            ),
            "salinity": (
                ("row",), np.array([34.1, 34.3, 34.5, 34.7],
                                    dtype=np.float64),
                {"units": "1e-3"},
            ),
        },
        coords={
            "time": ("row", np.array(
                ["2026-02-01T00:00", "2026-02-01T00:02",
                 "2026-02-01T00:04", "2026-02-01T00:06"],
                dtype="datetime64[ms]")),
            "latitude": ("row", [12.0, 12.01, 12.02, 12.03],
                         {"units": "degrees_north"}),
            "longitude": ("row", [84.0, 84.01, 84.02, 84.03],
                          {"units": "degrees_east"}),
            "depth": ("row", [0.0, 15.0, 30.0, 45.0], {"units": "m"}),
            "trajectory": ("row", ["ru29"] * 4),
            "profile_id": ("row", np.array([12, 12, 12, 12], dtype=np.int32)),
            "temperature_qc": (
                "row", np.array(["GOOD", "GOOD", "SUSPECT", "GOOD"],
                                dtype=object)),
        },
    )


def glider_descriptor(*, positive: str = "down") -> ObservationDatasetDescriptor:
    return ObservationDatasetDescriptor(
        identity=DatasetIdentity("ru29-20240419T1430", GLIDER_VERSION),
        sample_dimension="row",
        coordinates=ObservationCoordinateRoles(
            platform="trajectory", cycle="profile_id", longitude="longitude",
            latitude="latitude", time="time", vertical="depth",
        ),
        vertical=ObservationVertical(kind="depth", positive=positive),
        crs="EPSG:4326",
        qc_variables={"temperature": "temperature_qc"},
        provenance={"import_id": GLIDER_VERSION,
                    "source": "IOOS Glider DAC"},
    )


def glider_selection(*variables: str) -> ObservationProfileSelection:
    return ObservationProfileSelection(
        identity=ObservationProfileIdentity("ru29", "12"),
        variables=tuple(variables) or ("temperature",),
    )
