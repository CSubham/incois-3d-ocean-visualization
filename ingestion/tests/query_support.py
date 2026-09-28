"""Shared model-query fixtures and guarded local PostGIS setup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
import xarray as xr
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ingestion.canonical import collect_metadata
from ingestion.domain.package import (
    CanonicalPackage, CoordinateSet, DatasetGeometry, SourceInfo, VariableSpec,
)
from ingestion.domain.selection import (
    Area, DepthRange, ImportSelection, TimeRange,
)
from ingestion.domain.validation import ValidationResult
from ingestion.query import (
    DatasetExtent, DatasetVersionSummary, ModelFieldDescriptor,
    ModelFieldQuery, VariableSummary,
)
from ingestion.query_memory import (
    InMemoryDatasetVersion, InMemoryModelFieldQuery,
)


MODEL_VERSION_ID = "model-version-1"
PROFILE_VERSION_ID = "profile-version-1"
UNDECLARED_VERSION_ID = "undeclared-version-1"
LIVE_DATABASE = "incois_s3_query_live_test"
LIVE_PORT = "5433"


@dataclass(frozen=True)
class QueryContractCase:
    query: ModelFieldQuery
    model_version_id: str
    profile_version_id: str
    undeclared_query: ModelFieldQuery
    undeclared_version_id: str


def model_dataset() -> xr.Dataset:
    values = np.arange(24, dtype=np.float32).reshape(1, 3, 2, 4) + 20.0
    values[0, 1, 1, 2] = np.nan
    salinity = values + np.float32(10.0)
    dataset = xr.Dataset(
        {
            "water_temp": (
                ("time", "depth", "lat", "lon"), values,
                {
                    "units": "degree_Celsius",
                    "standard_name": "sea_water_temperature",
                },
            ),
            "salinity": (
                ("time", "depth", "lat", "lon"), salinity,
                {
                    "units": "1e-3",
                    "standard_name": "sea_water_salinity",
                },
            ),
        },
        coords={
            "time": np.array(["2026-09-28T00:00:00"],
                             dtype="datetime64[ns]"),
            "depth": (
                "depth", [0.0, 10.0, 20.0],
                {"units": "m", "positive": "down"},
            ),
            "lat": ("lat", [8.0, 9.0], {"units": "degrees_north"}),
            "lon": (
                "lon", [72.0, 73.0, 74.0, 75.0],
                {"units": "degrees_east"},
            ),
        },
        attrs={"title": "Managed model query fixture"},
    )
    dataset["water_temp"].encoding["_FillValue"] = -9999.0
    dataset["salinity"].encoding["_FillValue"] = -999.0
    return dataset


def profile_dataset() -> xr.Dataset:
    return xr.Dataset(
        {
            "TEMP": (
                ("observation",), [28.0, 27.5],
                {"units": "degree_Celsius"},
            ),
        },
        coords={
            "time": (
                "observation",
                np.array(["2026-09-28", "2026-09-28"],
                         dtype="datetime64[ns]"),
            ),
            "PRES": ("observation", [2.0, 10.0], {"units": "m"}),
            "latitude": ("observation", [8.5, 8.5]),
            "longitude": ("observation", [73.5, 73.5]),
            "PLATFORM_NUMBER": ("observation", [7902250, 7902250]),
            "CYCLE_NUMBER": ("observation", [12, 12]),
        },
    )


def model_package(import_id: str = MODEL_VERSION_ID,
                  dataset: xr.Dataset | None = None) -> CanonicalPackage:
    stored = model_dataset() if dataset is None else dataset
    coordinates = CoordinateSet(
        time="time", vertical="depth", latitude="lat", longitude="lon")
    dimensions = ("time", "depth", "lat", "lon")
    return CanonicalPackage(
        import_id=import_id,
        dataset=stored,
        geometry=DatasetGeometry.GRID,
        variables=tuple(
            VariableSpec(
                name=name,
                original_name=name,
                units=str(stored[name].attrs["units"]),
                standard_name=stored[name].attrs.get("standard_name"),
                dimensions=dimensions,
                fill_value=stored[name].encoding.get("_FillValue"),
            )
            for name in ("water_temp", "salinity")
        ),
        coordinates=coordinates,
        source=SourceInfo(
            source_id="hycom_opendap",
            source_name="HYCOM",
            dataset_id="GLBy0.08_expt_93.0",
            dataset_name="HYCOM GLBy0.08 global analysis",
            kind="remote",
            location="https://example.invalid/hycom",
            details={
                "provider": "contract fixture",
                "url": "https://example.invalid/hycom",
            },
        ),
        selection=ImportSelection(
            source_id="hycom_opendap",
            dataset_id="GLBy0.08_expt_93.0",
            variables=("water_temp", "salinity"),
            time=TimeRange(
                "2026-09-28T00:00:00Z", "2026-09-28T00:00:00Z"),
            depth=DepthRange(0.0, 20.0),
            area=Area(72.0, 75.0, 8.0, 9.0),
        ),
        validation=ValidationResult(
            checks_run=("coordinates_identified", "units_present")),
        metadata=collect_metadata(stored, coordinates),
    )


def profile_package(
        import_id: str = PROFILE_VERSION_ID) -> CanonicalPackage:
    dataset = profile_dataset()
    coordinates = CoordinateSet(
        time="time", vertical="PRES", latitude="latitude",
        longitude="longitude",
    )
    return CanonicalPackage(
        import_id=import_id,
        dataset=dataset,
        geometry=DatasetGeometry.PROFILE,
        variables=(VariableSpec(
            name="TEMP", original_name="TEMP", units="degree_Celsius",
            dimensions=("observation",),
        ),),
        coordinates=coordinates,
        source=SourceInfo(
            source_id="incois_erddap", source_name="INCOIS ERDDAP",
            dataset_id="Indian_ARGO_Floats", dataset_name="Indian Argo",
            kind="remote", details={"provider": "contract fixture"},
        ),
        selection=ImportSelection(
            source_id="incois_erddap", dataset_id="Indian_ARGO_Floats",
            variables=("TEMP",),
        ),
        validation=ValidationResult(checks_run=("coordinates_identified",)),
        metadata=collect_metadata(dataset, coordinates),
    )


def in_memory_case() -> QueryContractCase:
    dataset = model_dataset()
    extent = DatasetExtent(
        time_start="2026-09-28T00:00:00+00:00",
        time_end="2026-09-28T00:00:00+00:00",
        depth_min=0.0, depth_max=20.0,
        west=72.0, east=75.0, south=8.0, north=9.0,
    )
    summary = DatasetVersionSummary(
        id=MODEL_VERSION_ID,
        dataset="GLBy0.08_expt_93.0",
        geometry="grid",
        variables=(
            VariableSummary("salinity", "1e-3"),
            VariableSummary("water_temp", "degree_Celsius"),
        ),
        depth_levels=3,
        time_steps=1,
        extent=extent,
        created_at="2026-09-28T00:00:00+00:00",
    )

    def descriptor(name: str) -> ModelFieldDescriptor:
        return ModelFieldDescriptor(
            dataset_id="GLBy0.08_expt_93.0",
            dataset_version_id=MODEL_VERSION_ID,
            source_id="hycom_opendap",
            variable=name,
            units=str(dataset[name].attrs["units"]),
            standard_name=dataset[name].attrs.get("standard_name"),
            time_coordinate="time", depth_coordinate="depth",
            latitude_coordinate="lat", longitude_coordinate="lon",
            crs="EPSG:4326", vertical_positive="down",
            provenance={
                "import_id": MODEL_VERSION_ID,
                "source": {"id": "hycom_opendap"},
                "selection": {"variables": [name]},
                "validation": {"passed": True},
                "created_at": "2026-09-28T00:00:00+00:00",
            },
        )

    valid = InMemoryDatasetVersion(
        summary=summary,
        dataset=dataset,
        descriptors={
            name: descriptor(name) for name in ("water_temp", "salinity")
        },
    )
    profile = InMemoryDatasetVersion(
        summary=DatasetVersionSummary(
            id=PROFILE_VERSION_ID,
            dataset="Indian_ARGO_Floats",
            geometry="profile",
            variables=(VariableSummary("TEMP", "degree_Celsius"),),
            depth_levels=2, time_steps=2, extent=extent,
            created_at="2026-09-28T00:00:00+00:00",
        ),
        dataset=profile_dataset(),
        descriptors={},
    )
    undeclared = InMemoryDatasetVersion(
        summary=DatasetVersionSummary(
            id=UNDECLARED_VERSION_ID,
            dataset=summary.dataset,
            geometry="grid",
            variables=summary.variables,
            depth_levels=summary.depth_levels,
            time_steps=summary.time_steps,
            extent=summary.extent,
            created_at=summary.created_at,
        ),
        dataset=dataset,
        descriptors={},
        undeclared_references={"water_temp": "a coordinate reference system"},
    )
    query = InMemoryModelFieldQuery((valid, profile, undeclared))
    return QueryContractCase(
        query=query,
        model_version_id=MODEL_VERSION_ID,
        profile_version_id=PROFILE_VERSION_ID,
        undeclared_query=query,
        undeclared_version_id=UNDECLARED_VERSION_ID,
    )


def live_dsn_status() -> tuple[str | None, str | None]:
    dsn = os.environ.get("INGESTION_CATALOGUE_DSN")
    if not dsn:
        return None, "INGESTION_CATALOGUE_DSN is not set"
    try:
        parameters = _validated_live_parameters(dsn)
        admin = make_conninfo(**{**parameters, "dbname": "postgres"})
        with psycopg.connect(admin, connect_timeout=3) as connection:
            connection.execute("SELECT 1")
    except Exception as exc:
        return None, f"local PostGIS is not reachable: {type(exc).__name__}"
    return dsn, None


def rebuild_live_catalogue(dsn: str) -> Mapping[str, Any]:
    parameters = _validated_live_parameters(dsn)
    admin = make_conninfo(**{**parameters, "dbname": "postgres"})
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (LIVE_DATABASE,),
        )
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(
            sql.Identifier(LIVE_DATABASE)))
        connection.execute(sql.SQL("CREATE DATABASE {}").format(
            sql.Identifier(LIVE_DATABASE)))

    schema_path = Path(__file__).parents[1] / "storage" / "schema.sql"
    with psycopg.connect(dsn) as connection:
        connection.execute(schema_path.read_text(encoding="utf-8"))
        extension = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'postgis'"
        ).fetchone()
        tables = {
            row[0] for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ).fetchall()
        }
    expected = {"dataset_version", "dataset_variable", "observation_profile"}
    if extension is None or not expected.issubset(tables):
        raise RuntimeError("the live catalogue schema did not initialize")
    return {
        "postgis": str(extension[0]),
        "tables": sorted(expected),
    }


def _validated_live_parameters(dsn: str) -> dict[str, str]:
    parameters = conninfo_to_dict(dsn)
    if parameters.get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("live tests require a loopback PostgreSQL host")
    if parameters.get("port", "5432") != LIVE_PORT:
        raise ValueError(f"live tests require local port {LIVE_PORT}")
    if parameters.get("dbname") != LIVE_DATABASE:
        raise ValueError(
            f"live tests require disposable database {LIVE_DATABASE!r}")
    return parameters
