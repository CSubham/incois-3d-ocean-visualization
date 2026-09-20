"""The real storage layer.

Arrays go to the object store; what they are and where they came from goes
to the catalogue; observation positions go to PostGIS so an instrument can be
found by where it was rather than by opening every array.

Nothing here is updated in place. A version is written once, and a repeat
import is a new version.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
import psycopg
import xarray as xr
from psycopg.types.json import Jsonb

from ingestion.domain.errors import IngestionError
from ingestion.domain.package import CanonicalPackage, DatasetGeometry
from ingestion.ports import StoragePort, StorageReceipt
from ingestion.storage.objects import ObjectStore

#: Shapes that describe instruments rather than fields. Only these produce
#: profile records -- a gridded model field has no instrument to locate.
_INSTRUMENT_SHAPES = (DatasetGeometry.PROFILE, DatasetGeometry.TRAJECTORY,
                      DatasetGeometry.TRAJECTORY_PROFILE, DatasetGeometry.POINT)

#: Coordinate names that identify which platform took a measurement.
_PLATFORM_HINTS = ("platform_number", "platform", "wmo", "float", "trajectory",
                   "glider", "station")
_CYCLE_HINTS = ("cycle_number", "cycle", "profile_id", "profile", "cast")


class StorageError(IngestionError):
    """A package could not be stored."""


class PostgresStorage(StoragePort):
    """Object store for arrays, PostgreSQL and PostGIS for everything else."""

    def __init__(self, dsn: str, objects: ObjectStore) -> None:
        self.dsn = dsn
        self.objects = objects

    def hand_off(self, package: CanonicalPackage) -> StorageReceipt:
        # The array is written first. A catalogue row pointing at nothing is
        # worse than an orphaned array, which is merely wasted space.
        reference = self.objects.put(package.import_id, package.dataset)

        profiles = (_profiles_in(package)
                    if package.geometry in _INSTRUMENT_SHAPES else [])
        extent = _extent_of(package)

        try:
            with psycopg.connect(self.dsn) as connection:
                with connection.cursor() as cursor:
                    self._record_version(cursor, package, reference, extent)
                    self._record_variables(cursor, package)
                    self._record_profiles(cursor, package, profiles)
                connection.commit()
        except psycopg.Error as exc:
            raise StorageError(
                f"the catalogue rejected this import: {exc}") from exc

        return StorageReceipt(
            import_id=package.import_id,
            reference=reference,
            accepted_at=datetime.now(timezone.utc).isoformat(),
            details={"object_ref": reference,
                     "variables": len(package.variables),
                     "profiles": len(profiles),
                     "footprint": extent.get("footprint")},
        )

    # -- writes -------------------------------------------------------------

    @staticmethod
    def _record_version(cursor, package: CanonicalPackage, reference: str,
                        extent: dict[str, Any]) -> None:
        selection = package.selection
        cursor.execute(
            """
            INSERT INTO dataset_version (
                import_id, source_id, source_name, dataset_id, dataset_name,
                source_kind, geometry, object_ref, location, sizes,
                selection, validation, metadata, source_details,
                time_start, time_end, depth_min, depth_max, footprint)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, ST_GeogFromText(%s))
            """,
            (package.import_id, package.source.source_id,
             package.source.source_name, package.source.dataset_id,
             package.source.dataset_name, package.source.kind,
             package.geometry.value, reference, package.source.location,
             Jsonb({str(k): int(v) for k, v in package.dataset.sizes.items()}),
             Jsonb({"variables": list(selection.variables),
                    "time": vars(selection.time) if selection.time else None,
                    "depth": vars(selection.depth) if selection.depth else None,
                    "area": vars(selection.area) if selection.area else None}),
             Jsonb({"passed": package.validation.passed,
                    "checks_run": list(package.validation.checks_run)}),
             Jsonb(_plain(package.metadata)),
             Jsonb(_plain(package.source.details)),
             extent.get("time_start"), extent.get("time_end"),
             extent.get("depth_min"), extent.get("depth_max"),
             extent.get("footprint")))

    @staticmethod
    def _record_variables(cursor, package: CanonicalPackage) -> None:
        cursor.executemany(
            """
            INSERT INTO dataset_variable (
                import_id, name, original_name, units, standard_name,
                long_name, dimensions, fill_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [(package.import_id, spec.name, spec.original_name, spec.units,
              spec.standard_name, spec.long_name, list(spec.dimensions),
              _as_float(spec.fill_value)) for spec in package.variables])

    @staticmethod
    def _record_profiles(cursor, package: CanonicalPackage,
                         profiles: list[dict[str, Any]]) -> None:
        if not profiles:
            return
        cursor.executemany(
            """
            INSERT INTO observation_profile (
                import_id, platform_id, cycle, observed_at, position,
                depth_min, depth_max, measurements)
            VALUES (%s, %s, %s, %s, ST_MakePoint(%s, %s)::geography, %s, %s, %s)
            """,
            [(package.import_id, p["platform_id"], p["cycle"], p["observed_at"],
              p["longitude"], p["latitude"], p["depth_min"], p["depth_max"],
              p["measurements"]) for p in profiles])


# -- deriving what the catalogue needs ---------------------------------------

def _coordinate(package: CanonicalPackage, role: str) -> Optional[xr.DataArray]:
    name = getattr(package.coordinates, role, None)
    if name and name in package.dataset.variables:
        return package.dataset[name]
    return None


def _extent_of(package: CanonicalPackage) -> dict[str, Any]:
    """The bounds of what was stored, so downstream can search without opening it."""
    extent: dict[str, Any] = {}

    time = _coordinate(package, "time")
    if time is not None and time.size:
        stamps = pd.to_datetime(np.atleast_1d(time.values), errors="coerce", utc=True)
        stamps = stamps.dropna()
        if len(stamps):
            extent["time_start"] = stamps.min().to_pydatetime()
            extent["time_end"] = stamps.max().to_pydatetime()

    vertical = _coordinate(package, "vertical")
    if vertical is not None and vertical.size:
        extent["depth_min"] = _as_float(np.nanmin(vertical.values))
        extent["depth_max"] = _as_float(np.nanmax(vertical.values))

    latitude = _coordinate(package, "latitude")
    longitude = _coordinate(package, "longitude")
    if latitude is not None and longitude is not None \
            and latitude.size and longitude.size:
        south, north = _as_float(np.nanmin(latitude.values)), _as_float(np.nanmax(latitude.values))
        west, east = _as_float(np.nanmin(longitude.values)), _as_float(np.nanmax(longitude.values))
        if None not in (south, north, west, east):
            # Longitudes are stored signed, whatever convention the source used.
            west, east = _signed(west), _signed(east)
            if west > east:
                west, east = east, west
            extent["footprint"] = (
                f"SRID=4326;POLYGON(({west} {south}, {east} {south}, "
                f"{east} {north}, {west} {north}, {west} {south}))")
    return extent


def _profiles_in(package: CanonicalPackage) -> list[dict[str, Any]]:
    """Group observation rows into the casts they came from.

    Grouped by platform and cycle where the source supplied them. Without
    those a set of rows cannot be split into casts, so it is recorded as one
    profile rather than invented into several.
    """
    dataset = package.dataset
    latitude = _coordinate(package, "latitude")
    longitude = _coordinate(package, "longitude")
    if latitude is None or longitude is None:
        return []

    frame = pd.DataFrame({
        "latitude": np.atleast_1d(latitude.values).astype(float),
        "longitude": np.atleast_1d(longitude.values).astype(float),
    })
    vertical = _coordinate(package, "vertical")
    frame["depth"] = (np.atleast_1d(vertical.values).astype(float)
                      if vertical is not None else np.nan)
    time = _coordinate(package, "time")
    frame["observed_at"] = (pd.to_datetime(np.atleast_1d(time.values),
                                           errors="coerce", utc=True)
                            if time is not None else pd.NaT)

    platform = _named(dataset, _PLATFORM_HINTS)
    cycle = _named(dataset, _CYCLE_HINTS)
    frame["platform_id"] = (_as_text(dataset[platform]) if platform else None)
    frame["cycle"] = (_as_text(dataset[cycle]) if cycle else None)

    keys = [k for k in ("platform_id", "cycle") if frame[k].notna().any()]
    groups = (frame.groupby(keys, dropna=False) if keys
              else [((None, None), frame)])

    profiles: list[dict[str, Any]] = []
    for key, rows in (groups if keys else groups):
        values = key if isinstance(key, tuple) else (key,)
        named = dict(zip(keys, [str(v) if v is not None else None for v in values]))
        stamps = rows["observed_at"].dropna()
        profiles.append({
            "platform_id": named.get("platform_id"),
            "cycle": named.get("cycle"),
            "observed_at": stamps.min().to_pydatetime() if len(stamps) else None,
            "latitude": float(rows["latitude"].mean()),
            "longitude": _signed(float(rows["longitude"].mean())),
            "depth_min": _as_float(rows["depth"].min()),
            "depth_max": _as_float(rows["depth"].max()),
            "measurements": int(len(rows)),
        })
    return profiles


def _named(dataset: xr.Dataset, hints: tuple[str, ...]) -> Optional[str]:
    for name in dataset.variables:
        if str(name).lower() in hints:
            return str(name)
    for name in dataset.variables:
        if any(hint in str(name).lower() for hint in hints):
            return str(name)
    return None


def _as_text(array: xr.DataArray) -> pd.Series:
    return pd.Series(np.atleast_1d(array.values)).astype(str)


def _signed(longitude: float) -> float:
    """Longitude as -180 to 180, whatever the source used."""
    return longitude - 360.0 if longitude > 180.0 else longitude


def _as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else number


def _plain(value: Any) -> Any:
    """Make numpy scalars serialisable."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (np.ndarray,)):
        return [_plain(v) for v in value.tolist()]
    return value
