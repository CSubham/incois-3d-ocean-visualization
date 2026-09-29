"""PostgreSQL catalogue and ObjectStore scientific query adapter."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import psycopg
import xarray as xr
from psycopg.rows import dict_row

from ingestion.query import (
    DatasetExtent, DatasetVersionListing, DatasetVersionSummary,
    ManagedModelField, ModelFieldDescriptor, ModelFieldQueryError,
    NotAModelField, NotAnObservationProfile, ObservationProfile,
    ObservationVersionDescriptor, ObservationVersionListing,
    observation_vertical_kind,
    ProfileIdentity, ProfileMarker, ProfileNotFound, ProfileSearch,
    ProfileValue, ProfileVariable, ScientificQuery,
    UnavailableDatasetVersion, UndeclaredReference, VariableSummary,
    VariableUnavailable, VersionNotFound,
)
from ingestion.storage.objects import ObjectStore


_VERSION_COLUMNS = """
    import_id, source_id, source_name, dataset_id, dataset_name,
    source_kind, geometry, object_ref, sizes, selection, validation,
    metadata, source_details, time_values, depth_values,
    time_start, time_end,
    vertical_min, vertical_max, vertical_kind, vertical_units,
    depth_min, depth_max,
    created_at,
    ST_XMin(Box2D(footprint::geometry)) AS west,
    ST_XMax(Box2D(footprint::geometry)) AS east,
    ST_YMin(Box2D(footprint::geometry)) AS south,
    ST_YMax(Box2D(footprint::geometry)) AS north
"""
_LIST_VERSIONS_SQL = f"""
SELECT {_VERSION_COLUMNS}
FROM dataset_version
WHERE geometry = %s
ORDER BY created_at DESC, import_id DESC
"""
_LIST_OBSERVATION_VERSIONS_SQL = f"""
SELECT {_VERSION_COLUMNS}
FROM dataset_version
WHERE geometry = ANY(%s)
ORDER BY created_at DESC, import_id DESC
"""
_VERSION_SQL = f"""
SELECT {_VERSION_COLUMNS}
FROM dataset_version
WHERE import_id = %s
"""
_VARIABLES_SQL = """
SELECT import_id, name, units, standard_name
FROM dataset_variable
WHERE import_id = ANY(%s)
ORDER BY import_id, name
"""
_PROFILE_MARKERS_SQL = """
SELECT import_id, platform_id, cycle, observed_at,
       representative_source_index,
       ST_X(position::geometry) AS longitude,
       ST_Y(position::geometry) AS latitude
FROM observation_profile
WHERE platform_id IS NOT NULL
  AND cycle IS NOT NULL
  AND observed_at >= %s
  AND observed_at <= %s
  AND ST_Intersects(
      position,
      ST_MakeEnvelope(%s, %s, %s, %s, 4326)::geography)
ORDER BY observed_at, import_id, platform_id, cycle
"""
_PROFILE_SQL = """
SELECT import_id, platform_id, cycle, observed_at,
       representative_source_index,
       ST_X(position::geometry) AS longitude,
       ST_Y(position::geometry) AS latitude
FROM observation_profile
WHERE import_id = %s AND platform_id = %s AND cycle = %s
"""

_REQUIRED_COORDINATES = ("time", "vertical", "latitude", "longitude")
_OBSERVATION_GEOMETRIES = {"profile", "trajectory", "trajectory_profile",
                           "point"}
_PLATFORM_HINTS = ("platform_number", "platform", "wmo", "float",
                   "trajectory", "glider", "station")
_CYCLE_HINTS = ("cycle_number", "cycle", "profile_id", "profile", "cast")
_SENSITIVE_KEY_PARTS = (
    "path", "object", "dsn", "connection", "cursor", "sql", "bucket",
    "container", "credential", "password", "secret", "token",
)
_STORAGE_ENCODING_KEY_PARTS = (
    "source", "path", "filename", "object", "dsn", "bucket", "container",
)
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_CONNECTION_STRING = re.compile(
    r"(?:^|\s)(?:host|hostaddr|port|dbname|user|password)\s*=",
    re.IGNORECASE,
)
_SENSITIVE_SCHEMES = {
    "abfs", "abfss", "azure", "file", "gs", "postgres", "postgresql", "s3",
}
_OMIT = object()


class CatalogueModelFieldQuery(ScientificQuery):
    """Read managed fields and profiles without leaking backend details."""

    def __init__(
        self,
        catalogue_dsn: str,
        objects: ObjectStore,
        source_references: Mapping[str, Any],
        *,
        connect: Callable[[str], Any] | None = None,
        connect_timeout: int = 5,
    ) -> None:
        self._catalogue_dsn = catalogue_dsn
        self._objects = objects
        self._source_references = dict(source_references)
        self._connect = connect
        self._connect_timeout = connect_timeout

    def list_model_versions(self) -> DatasetVersionListing:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_LIST_VERSIONS_SQL, ("grid",))
                    versions = tuple(cursor.fetchall())
                    variables = self._variables(cursor, [
                        str(row["import_id"]) for row in versions
                    ])
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                "the model-field catalogue could not be read") from None

        summaries: list[DatasetVersionSummary] = []
        unavailable: list[UnavailableDatasetVersion] = []
        for version in versions:
            version_id = str(version["import_id"])
            try:
                summaries.append(self._summary_for_version(
                    version, variables[version_id]))
            except ModelFieldQueryError as exc:
                unavailable.append(UnavailableDatasetVersion(
                    version_id, str(exc)))
            except Exception:
                unavailable.append(UnavailableDatasetVersion(
                    version_id,
                    "the managed dataset version could not be read",
                ))
        return DatasetVersionListing(
            versions=tuple(summaries),
            unavailable=tuple(unavailable),
        )

    def describe_version(
            self, dataset_version_id: str) -> DatasetVersionSummary:
        version, variables = self._version(dataset_version_id)
        _require_grid(version)
        return self._summary_for_version(version, variables)

    def open_model_field(
            self, dataset_version_id: str,
            variable: str) -> ManagedModelField:
        version, variables = self._version(dataset_version_id)
        _require_grid(version)
        declared = next(
            (item for item in variables if item["name"] == variable), None)
        if declared is None:
            raise VariableUnavailable(dataset_version_id, variable)

        reference = version.get("object_ref")
        if not isinstance(reference, str) or not reference:
            raise UndeclaredReference(
                dataset_version_id, "a managed scientific object")
        try:
            source_dataset = self._objects.open(reference)
        except Exception:
            raise ModelFieldQueryError(
                "the managed scientific object could not be opened") from None

        try:
            if variable not in source_dataset.data_vars:
                raise VariableUnavailable(dataset_version_id, variable)
            descriptor, grid_mapping = _descriptor(
                version, declared, source_dataset,
                self._source_references.get(str(version["source_id"])),
            )
            selected = [variable]
            if (grid_mapping is not None
                    and grid_mapping in source_dataset.data_vars):
                selected.append(grid_mapping)
            dataset = source_dataset[selected]
            _remove_storage_references(dataset)
            return ManagedModelField(
                dataset, descriptor, close=source_dataset.close)
        except ModelFieldQueryError:
            _close_quietly(source_dataset)
            raise
        except Exception:
            _close_quietly(source_dataset)
            raise ModelFieldQueryError(
                "the managed scientific object could not be decoded") from None

    def list_observation_versions(self) -> ObservationVersionListing:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_LIST_OBSERVATION_VERSIONS_SQL,
                                   (sorted(_OBSERVATION_GEOMETRIES),))
                    versions = tuple(cursor.fetchall())
                    variables = self._variables(cursor, [
                        str(row["import_id"]) for row in versions])
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                "the observation catalogue could not be read") from None
        described: list[ObservationVersionDescriptor] = []
        unavailable: list[UnavailableDatasetVersion] = []
        for version in versions:
            version_id = str(version["import_id"])
            try:
                described.append(_observation_descriptor(
                    version, variables[version_id],
                    self._source_references.get(str(version["source_id"]))))
            except (ModelFieldQueryError, ValueError) as exc:
                unavailable.append(UnavailableDatasetVersion(version_id, str(exc)))
        return ObservationVersionListing(tuple(described), tuple(unavailable))

    def describe_observation_version(
            self, dataset_version_id: str) -> ObservationVersionDescriptor:
        version, variables = self._version(dataset_version_id)
        _require_observation_profile(version)
        return _observation_descriptor(
            version, variables,
            self._source_references.get(str(version["source_id"])))

    def find_profile_markers(
            self, search: ProfileSearch) -> tuple[ProfileMarker, ...]:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_PROFILE_MARKERS_SQL, (
                        search.time_start, search.time_end,
                        search.west, search.south, search.east, search.north,
                    ))
                    rows = tuple(cursor.fetchall())
            return tuple(_profile_marker(row) for row in rows)
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                "the observation-profile catalogue could not be read") from None

    def get_profile(self, identity: ProfileIdentity) -> ObservationProfile:
        record = self._profile_record(identity)
        version, variables = self._version(identity.dataset_version_id)
        _require_observation_profile(version)
        reference = version.get("object_ref")
        if not isinstance(reference, str) or not reference:
            raise UndeclaredReference(
                identity.dataset_version_id, "a managed scientific object")
        try:
            source_dataset = self._objects.open(reference)
        except Exception:
            raise ModelFieldQueryError(
                "the managed observation object could not be opened") from None
        try:
            return _observation_profile(
                version, variables, source_dataset, identity, record)
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                "the managed observation profile could not be decoded") from None
        finally:
            _close_quietly(source_dataset)

    def _summary_from_object(
        self,
        version: Mapping[str, Any],
        variables: Sequence[Mapping[str, Any]],
    ) -> DatasetVersionSummary:
        version_id = str(version["import_id"])
        reference = version.get("object_ref")
        if not isinstance(reference, str) or not reference:
            raise UndeclaredReference(
                version_id, "a managed scientific object")
        try:
            dataset = self._objects.open(reference)
        except Exception:
            raise ModelFieldQueryError(
                f"dataset version {version_id!r} could not be opened") from None
        try:
            return _summary(version, variables, dataset)
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                f"dataset version {version_id!r} could not be decoded") from None
        finally:
            _close_quietly(dataset)

    def _summary_for_version(
        self,
        version: Mapping[str, Any],
        variables: Sequence[Mapping[str, Any]],
    ) -> DatasetVersionSummary:
        if (version.get("time_values") is not None
                and version.get("depth_values") is not None):
            return _summary(version, variables)
        return self._summary_from_object(version, variables)

    def _profile_record(
            self, identity: ProfileIdentity) -> Mapping[str, Any]:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_PROFILE_SQL, (
                        identity.dataset_version_id,
                        identity.platform_id,
                        identity.cycle,
                    ))
                    rows = tuple(cursor.fetchall())
        except Exception:
            raise ModelFieldQueryError(
                "the observation-profile catalogue could not be read") from None
        if not rows:
            raise ProfileNotFound(identity)
        if len(rows) != 1:
            raise ModelFieldQueryError(
                "the requested observation-profile identity is ambiguous")
        return rows[0]

    def _version(
        self, dataset_version_id: str,
    ) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_VERSION_SQL, (dataset_version_id,))
                    version = cursor.fetchone()
                    if version is None:
                        raise VersionNotFound(dataset_version_id)
                    variables = self._variables(cursor, [dataset_version_id])[
                        dataset_version_id
                    ]
                    return version, variables
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                "the model-field catalogue could not be read") from None

    @staticmethod
    def _variables(cursor, dataset_version_ids: Sequence[str]
                   ) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
        grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        if dataset_version_ids:
            cursor.execute(_VARIABLES_SQL, (list(dataset_version_ids),))
            for row in cursor.fetchall():
                grouped[str(row["import_id"])].append(row)
        return {
            version_id: tuple(grouped[version_id])
            for version_id in dataset_version_ids
        }

    def _connection(self):
        if self._connect is not None:
            return self._connect(self._catalogue_dsn)
        return psycopg.connect(self._catalogue_dsn, row_factory=dict_row,
                               connect_timeout=self._connect_timeout)


def _require_grid(version: Mapping[str, Any]) -> None:
    geometry = str(version.get("geometry", ""))
    if geometry != "grid":
        raise NotAModelField(str(version["import_id"]), geometry)


def _require_observation_profile(version: Mapping[str, Any]) -> None:
    geometry = str(version.get("geometry", ""))
    if geometry not in _OBSERVATION_GEOMETRIES:
        raise NotAnObservationProfile(str(version["import_id"]), geometry)


def _summary(version: Mapping[str, Any],
             variables: Sequence[Mapping[str, Any]],
             dataset: xr.Dataset | None = None) -> DatasetVersionSummary:
    version_id = str(version["import_id"])
    coordinate_names = _coordinate_names(version, version_id)
    sizes = _required_mapping(version, "sizes", version_id)
    try:
        depth_levels = int(sizes[coordinate_names["vertical"]])
        time_steps = int(sizes[coordinate_names["time"]])
    except (KeyError, TypeError, ValueError):
        raise UndeclaredReference(
            version_id, "time and depth coordinate dimensions") from None
    time_name = coordinate_names["time"]
    depth_name = coordinate_names["vertical"]
    if (version.get("time_values") is not None
            and version.get("depth_values") is not None):
        time_values = _catalogue_time_values(
            version["time_values"], version_id)
        depth_values = _catalogue_depth_values(
            version["depth_values"], version_id)
    else:
        if dataset is None:
            raise UndeclaredReference(
                version_id, "catalogued time and depth coordinate values")
        if time_name not in dataset.variables:
            raise UndeclaredReference(
                version_id, f"the time coordinate {time_name!r}")
        if depth_name not in dataset.variables:
            raise UndeclaredReference(
                version_id, f"the depth coordinate {depth_name!r}")
        time_values = _time_coordinate_values(dataset[time_name], version_id)
        depth_values = _depth_coordinate_values(dataset[depth_name], version_id)
    if len(time_values) != time_steps or len(depth_values) != depth_levels:
        raise UndeclaredReference(
            version_id, "coordinate values matching catalogue dimensions")
    return DatasetVersionSummary(
        id=version_id,
        dataset=str(version["dataset_id"]),
        geometry=str(version["geometry"]),
        variables=tuple(
            VariableSummary(
                name=str(item["name"]),
                units=(str(item["units"])
                       if item.get("units") is not None else None),
            )
            for item in variables
        ),
        depth_levels=depth_levels,
        time_steps=time_steps,
        depth_values=depth_values,
        time_values=time_values,
        extent=DatasetExtent(
            time_start=_iso(version.get("time_start")),
            time_end=_iso(version.get("time_end")),
            depth_min=_optional_float(version.get("depth_min")),
            depth_max=_optional_float(version.get("depth_max")),
            west=_optional_float(version.get("west")),
            east=_optional_float(version.get("east")),
            south=_optional_float(version.get("south")),
            north=_optional_float(version.get("north")),
            vertical_min=_optional_float(version.get("vertical_min")),
            vertical_max=_optional_float(version.get("vertical_max")),
            vertical_kind=_vertical_kind(version.get("vertical_kind")),
            vertical_units=_optional_text(version.get("vertical_units")),
        ),
        created_at=_iso(version.get("created_at")) or "",
    )


def _descriptor(
    version: Mapping[str, Any],
    variable: Mapping[str, Any],
    dataset: xr.Dataset,
    declaration: Any,
) -> tuple[ModelFieldDescriptor, str | None]:
    version_id = str(version["import_id"])
    variable_name = str(variable["name"])
    coordinate_names = _coordinate_names(version, version_id)
    for role, name in coordinate_names.items():
        if name not in dataset.variables:
            raise UndeclaredReference(
                version_id, f"the {role} coordinate {name!r}")

    units = variable.get("units")
    if not isinstance(units, str) or not units.strip():
        raise UndeclaredReference(
            version_id, f"units for variable {variable_name!r}")

    field = dataset[variable_name]
    grid_mapping = _grid_mapping_name(field)
    crs, crs_basis = _crs(
        dataset, field, grid_mapping, declaration, version_id)
    vertical_positive, vertical_basis = _vertical_positive(
        dataset[coordinate_names["vertical"]], declaration, version_id)

    provenance = _version_provenance(version, version_id, {
        "crs": crs_basis, "vertical_positive": vertical_basis})
    return ModelFieldDescriptor(
        dataset_id=str(version["dataset_id"]),
        dataset_version_id=version_id,
        source_id=str(version["source_id"]),
        variable=variable_name,
        units=units,
        standard_name=(str(variable["standard_name"])
                       if variable.get("standard_name") is not None else None),
        time_coordinate=coordinate_names["time"],
        depth_coordinate=coordinate_names["vertical"],
        latitude_coordinate=coordinate_names["latitude"],
        longitude_coordinate=coordinate_names["longitude"],
        crs=crs,
        vertical_positive=vertical_positive,
        provenance=provenance,
    ), grid_mapping


def _version_provenance(version: Mapping[str, Any], version_id: str,
                        reference_basis: Mapping[str, str]) -> dict[str, Any]:
    """Portable provenance of one stored version, shared by every descriptor."""
    metadata = _required_mapping(version, "metadata", version_id)
    source_details = _required_mapping(version, "source_details", version_id)
    return {
        "import_id": version_id,
        "source": {
            "id": str(version["source_id"]),
            "name": str(version["source_name"]),
            "dataset": str(version["dataset_id"]),
            "dataset_name": str(version["dataset_name"]),
            "kind": str(version["source_kind"]),
            "details": _portable_mapping(source_details),
        },
        "selection": _portable_mapping(
            _required_mapping(version, "selection", version_id)),
        "validation": _portable_mapping(
            _required_mapping(version, "validation", version_id)),
        "created_at": _iso(version.get("created_at")),
        "reference_basis": dict(reference_basis),
        "global_attributes": _portable_mapping(
            _mapping(metadata.get("global_attributes", {}),
                     version_id, "global attributes")),
    }


def _observation_descriptor(version: Mapping[str, Any],
                            variables: Sequence[Mapping[str, Any]],
                            declaration: Any) -> ObservationVersionDescriptor:
    """Describe an observation version from catalogue rows alone."""
    version_id = str(version["import_id"])
    metadata = _required_mapping(version, "metadata", version_id)
    names = _mapping(metadata.get("coordinate_names", {}), version_id,
                     "coordinate names")
    units = _mapping(metadata.get("coordinate_units", {}), version_id,
                     "coordinate units")
    vertical = names.get("vertical")
    if not isinstance(vertical, str) or not vertical.strip():
        raise UndeclaredReference(version_id, "the vertical coordinate name")
    vertical_units = units.get("vertical")
    kind = observation_vertical_kind(
        vertical_units if isinstance(vertical_units, str) else None)
    if kind is None:
        raise UndeclaredReference(
            version_id,
            f"vertical units that are a depth or a pressure, not "
            f"{vertical_units!r}")
    crs = _declaration_value(declaration, "crs")
    positive = _declaration_value(declaration, "vertical_positive")
    basis = _declaration_value(declaration, "basis")
    if not isinstance(crs, str) or not crs.strip():
        raise UndeclaredReference(version_id, "a coordinate reference system")
    if positive not in ("down", "up"):
        raise UndeclaredReference(version_id, "the vertical positive direction")
    if not isinstance(basis, str) or not basis.strip():
        raise UndeclaredReference(version_id, "the reference declaration basis")
    return ObservationVersionDescriptor(
        dataset_id=str(version["dataset_id"]),
        dataset_version_id=version_id,
        source_id=str(version["source_id"]),
        geometry=str(version["geometry"]),
        vertical_coordinate=vertical,
        vertical_units=str(vertical_units),
        vertical_kind=kind,
        crs=crs,
        vertical_positive=positive,
        variables=tuple(
            VariableSummary(name=str(item["name"]),
                            units=(str(item["units"]) if item.get("units")
                                   is not None else None))
            for item in variables),
        extent=DatasetExtent(
            time_start=_iso(version.get("time_start")),
            time_end=_iso(version.get("time_end")),
            depth_min=_optional_float(version.get("depth_min")),
            depth_max=_optional_float(version.get("depth_max")),
            west=_optional_float(version.get("west")),
            east=_optional_float(version.get("east")),
            south=_optional_float(version.get("south")),
            north=_optional_float(version.get("north")),
            vertical_min=_optional_float(version.get("vertical_min")),
            vertical_max=_optional_float(version.get("vertical_max")),
            vertical_kind=_vertical_kind(version.get("vertical_kind")),
            vertical_units=_optional_text(version.get("vertical_units")),
        ),
        created_at=_iso(version.get("created_at")) or "",
        provenance=_version_provenance(version, version_id, {
            "crs": basis, "vertical_positive": basis,
            "vertical_kind": f"units {vertical_units!r} of {vertical!r}"}),
    )


def _coordinate_names(version: Mapping[str, Any],
                      version_id: str) -> dict[str, str]:
    metadata = _required_mapping(version, "metadata", version_id)
    raw = _mapping(
        metadata.get("coordinate_names", {}), version_id, "coordinate names")
    names: dict[str, str] = {}
    for role in _REQUIRED_COORDINATES:
        value = raw.get(role)
        if not isinstance(value, str) or not value.strip():
            exposed_role = "depth" if role == "vertical" else role
            raise UndeclaredReference(
                version_id, f"the {exposed_role} coordinate name")
        names[role] = value
    if len(set(names.values())) != 4:
        raise UndeclaredReference(version_id, "distinct coordinate names")
    return names


def _grid_mapping_name(field: xr.DataArray) -> str | None:
    value = field.attrs.get("grid_mapping")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.split()[0].rstrip(":")


def _crs(dataset: xr.Dataset, field: xr.DataArray,
         grid_mapping: str | None, declaration: Any,
         version_id: str) -> tuple[str, str]:
    if grid_mapping is not None:
        if grid_mapping not in dataset.variables:
            raise UndeclaredReference(
                version_id, f"CF grid mapping {grid_mapping!r}")
        mapping = dataset[grid_mapping]
        for name in ("spatial_ref", "crs_wkt"):
            value = mapping.attrs.get(name)
            if isinstance(value, str) and value.strip():
                return value, f"CF grid_mapping {grid_mapping}.{name}"
        epsg = mapping.attrs.get("epsg_code")
        if epsg is not None and str(epsg).strip():
            value = str(epsg).strip()
            if value.isdigit():
                value = f"EPSG:{value}"
            return value, f"CF grid_mapping {grid_mapping}.epsg_code"
        name = mapping.attrs.get("grid_mapping_name")
        if isinstance(name, str) and name.strip():
            return f"CF:{name.strip()}", (
                f"CF grid_mapping {grid_mapping}.grid_mapping_name")
        raise UndeclaredReference(
            version_id, f"a usable CF grid mapping {grid_mapping!r}")

    declared = _declaration_value(declaration, "crs")
    basis = _declaration_value(declaration, "basis")
    if not isinstance(declared, str) or not declared.strip():
        raise UndeclaredReference(version_id, "a coordinate reference system")
    if not isinstance(basis, str) or not basis.strip():
        raise UndeclaredReference(version_id, "the CRS declaration basis")
    return declared, basis


def _vertical_positive(depth: xr.DataArray, declaration: Any,
                       version_id: str) -> tuple[str, str]:
    source_value = depth.attrs.get("positive")
    if source_value is not None:
        normalized = str(source_value).strip().lower()
        if normalized not in ("down", "up"):
            raise UndeclaredReference(
                version_id, "a valid CF vertical positive direction")
        return normalized, f"CF coordinate {depth.name}.positive"

    declared = _declaration_value(declaration, "vertical_positive")
    basis = _declaration_value(declaration, "basis")
    if declared not in ("down", "up"):
        raise UndeclaredReference(
            version_id, "the vertical positive direction")
    if not isinstance(basis, str) or not basis.strip():
        raise UndeclaredReference(
            version_id, "the vertical-direction declaration basis")
    return declared, basis


def _declaration_value(declaration: Any, name: str) -> Any:
    if isinstance(declaration, Mapping):
        return declaration.get(name)
    return getattr(declaration, name, None)


def _required_mapping(container: Mapping[str, Any], key: str,
                      version_id: str) -> Mapping[str, Any]:
    if key not in container:
        raise UndeclaredReference(version_id, key)
    return _mapping(container[key], version_id, key)


def _mapping(value: Any, version_id: str,
             description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UndeclaredReference(version_id, description)
    return value


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _vertical_kind(value: Any) -> str | None:
    rendered = _optional_text(value)
    return rendered if rendered in {"depth", "pressure"} else None


def _catalogue_time_values(value: Any,
                           version_id: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise UndeclaredReference(version_id, "catalogued time values")
    values = tuple(value)
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise UndeclaredReference(version_id, "catalogued ISO time values")
    return values


def _catalogue_depth_values(value: Any,
                            version_id: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        raise UndeclaredReference(version_id, "catalogued depth values")
    try:
        values = tuple(
            float(item) for item in value if not isinstance(item, bool))
    except (TypeError, ValueError):
        raise UndeclaredReference(
            version_id, "numeric catalogued depth values") from None
    if len(values) != len(value) or not all(np.isfinite(item) for item in values):
        raise UndeclaredReference(
            version_id, "finite numeric catalogued depth values")
    return values


def _time_coordinate_values(array: xr.DataArray,
                            version_id: str) -> tuple[str, ...]:
    if len(array.dims) != 1:
        raise UndeclaredReference(
            version_id, f"one-dimensional time coordinate {array.name!r}")
    values: list[str] = []
    for value in np.ravel(array.values):
        timestamp = _timestamp(value)
        if timestamp is None:
            raise UndeclaredReference(version_id, "complete time values")
        values.append(timestamp)
    return tuple(values)


def _depth_coordinate_values(array: xr.DataArray,
                             version_id: str) -> tuple[float, ...]:
    if len(array.dims) != 1:
        raise UndeclaredReference(
            version_id, f"one-dimensional depth coordinate {array.name!r}")
    try:
        values = tuple(float(value) for value in np.ravel(array.values))
    except (TypeError, ValueError):
        raise UndeclaredReference(version_id, "numeric depth values") from None
    if not all(np.isfinite(value) for value in values):
        raise UndeclaredReference(version_id, "finite depth values")
    return values


def _profile_marker(row: Mapping[str, Any]) -> ProfileMarker:
    version_id = str(row.get("import_id", ""))
    platform_id = row.get("platform_id")
    cycle = row.get("cycle")
    observed_at = _iso(row.get("observed_at"))
    if (not isinstance(platform_id, str) or not platform_id.strip()
            or not isinstance(cycle, str) or not cycle.strip()
            or observed_at is None):
        raise UndeclaredReference(version_id, "exact profile identity and time")
    try:
        longitude = float(row["longitude"])
        latitude = float(row["latitude"])
    except (KeyError, TypeError, ValueError):
        raise UndeclaredReference(version_id, "profile position") from None
    return ProfileMarker(
        identity=ProfileIdentity(version_id, platform_id, cycle),
        longitude=longitude,
        latitude=latitude,
        observed_at=observed_at,
        representative_source_index=(
            int(row["representative_source_index"])
            if row.get("representative_source_index") is not None else None
        ),
    )


def _observation_profile(
    version: Mapping[str, Any],
    variables: Sequence[Mapping[str, Any]],
    dataset: xr.Dataset,
    identity: ProfileIdentity,
    profile_record: Mapping[str, Any],
) -> ObservationProfile:
    version_id = identity.dataset_version_id
    if str(profile_record.get("import_id")) != version_id:
        raise ProfileNotFound(identity)
    names = _coordinate_names(version, version_id)
    for role, name in names.items():
        if name not in dataset.variables:
            exposed = "depth" if role == "vertical" else role
            raise UndeclaredReference(
                version_id, f"the {exposed} coordinate {name!r}")
    platform_name = _named(dataset, _PLATFORM_HINTS)
    cycle_name = _named(dataset, _CYCLE_HINTS)
    if platform_name is None or cycle_name is None:
        raise UndeclaredReference(
            version_id, "platform and cycle identity variables")
    platform = dataset[platform_name]
    cycle = dataset[cycle_name]
    if len(platform.dims) != 1 or cycle.dims != platform.dims:
        raise UndeclaredReference(
            version_id, "one-dimensional platform and cycle identity")
    sample_dim = platform.dims[0]
    platform_values = _text_values(platform.values)
    cycle_values = _text_values(cycle.values)
    positions = np.asarray([
        index for index, (platform_id, cycle_id) in enumerate(zip(
            platform_values, cycle_values, strict=True))
        if platform_id == identity.platform_id and cycle_id == identity.cycle
    ], dtype=np.intp)
    if not positions.size:
        raise ProfileNotFound(identity)
    selected = dataset.isel({sample_dim: positions})
    depth_name = names["vertical"]
    time_name = names["time"]
    return ObservationProfile(
        identity=identity,
        depth_coordinate=depth_name,
        depth_units=_optional_text(selected[depth_name].attrs.get("units")),
        depth_values=_profile_values(
            selected[depth_name], sample_dim, version_id),
        time_coordinate=time_name,
        timestamps=tuple(
            _timestamp(value)
            for value in np.ravel(selected[time_name].values)
        ),
        variables=tuple(
            _profile_variable(selected, variable, sample_dim, version_id)
            for variable in variables
        ),
        source_indices=tuple(int(index) for index in positions),
        depth_source_dtype=str(selected[depth_name].dtype),
        time_source_dtype=str(selected[time_name].dtype),
        time_encoding=_time_encoding(selected[time_name]),
    )


def _profile_variable(
    dataset: xr.Dataset,
    variable: Mapping[str, Any],
    sample_dim: str,
    version_id: str,
) -> ProfileVariable:
    name = str(variable["name"])
    if name not in dataset.variables:
        raise VariableUnavailable(version_id, name)
    quality_name = _quality_name(dataset, name)
    quality = dataset[quality_name] if quality_name is not None else None
    values = dataset[name]
    return ProfileVariable(
        name=name,
        units=_optional_text(variable.get("units")),
        values=_profile_values(values, sample_dim, version_id),
        source_dtype=str(values.dtype),
        quality_control_name=quality_name,
        quality_control=(
            _profile_values(quality, sample_dim, version_id)
            if quality is not None else None
        ),
        qc_source_dtype=(str(quality.dtype) if quality is not None else None),
        qc_flag_values=(
            _qc_flag_values(quality, version_id)
            if quality is not None else None
        ),
        qc_flag_meanings=(
            _optional_qc_text(quality, "flag_meanings", version_id)
            if quality is not None else None
        ),
        qc_conventions=(
            _optional_qc_text(quality, "conventions", version_id)
            if quality is not None else None
        ),
    )


def _profile_values(array: xr.DataArray, sample_dim: str,
                    version_id: str) -> tuple[ProfileValue, ...]:
    if array.dims != (sample_dim,):
        raise UndeclaredReference(
            version_id, f"one-dimensional profile variable {array.name!r}")
    return tuple(_profile_value(value) for value in np.ravel(array.values))


def _profile_value(value: Any) -> ProfileValue:
    if np.ma.is_masked(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and np.isnan(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _timestamp(value: Any) -> str | None:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return str(np.datetime_as_string(value, unit="ns"))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    plain = _profile_value(value)
    return str(plain) if plain is not None else None


def _named(dataset: xr.Dataset, hints: tuple[str, ...]) -> str | None:
    lowered = {str(name).lower(): str(name) for name in dataset.variables}
    for hint in hints:
        if hint in lowered:
            return lowered[hint]
    for name in dataset.variables:
        if any(hint in str(name).lower() for hint in hints):
            return str(name)
    return None


def _quality_name(dataset: xr.Dataset, variable: str) -> str | None:
    expected = f"{variable}_qc".lower()
    return next(
        (str(name) for name in dataset.variables
         if str(name).lower() == expected),
        None,
    )


def _qc_flag_values(array: xr.DataArray,
                    version_id: str) -> tuple[ProfileValue, ...] | None:
    if "flag_values" not in array.attrs:
        return None
    values = np.asarray(array.attrs["flag_values"], dtype=object)
    if values.ndim > 1:
        raise UndeclaredReference(
            version_id,
            f"scalar or vector QC flag_values on {array.name!r}",
        )
    return tuple(
        _qc_attribute_scalar(value, array.name, "flag_values", version_id)
        for value in values.reshape(-1)
    )


def _optional_qc_text(array: xr.DataArray, attribute: str,
                      version_id: str) -> str | None:
    if attribute not in array.attrs:
        return None
    value = _qc_attribute_scalar(
        array.attrs[attribute], array.name, attribute, version_id)
    if not isinstance(value, str):
        raise UndeclaredReference(
            version_id, f"text QC {attribute} on {array.name!r}")
    return value


def _qc_attribute_scalar(value: Any, variable: Any, attribute: str,
                         version_id: str) -> ProfileValue:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise UndeclaredReference(
                version_id, f"UTF-8 QC {attribute} on {variable!r}") from None
    if (not isinstance(value, (str, int, float, bool))
            or isinstance(value, float) and not np.isfinite(value)):
        raise UndeclaredReference(
            version_id,
            f"scalar text or numeric QC {attribute} on {variable!r}",
        )
    return value


def _text_values(values: Any) -> tuple[str, ...]:
    return tuple(str(_profile_value(value) or "")
                 for value in np.ravel(values))


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _time_encoding(array: xr.DataArray) -> Mapping[str, str | None]:
    return {
        "units": _optional_text(array.encoding.get("units")),
        "calendar": _optional_text(array.encoding.get("calendar")),
    }


def _portable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    withheld = False
    for key, item in value.items():
        name = str(key)
        normalized = name.lower().replace("-", "_")
        if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
            withheld = True
            continue
        portable = _portable_value(item)
        if portable is not _OMIT:
            cleaned[name] = portable
        else:
            withheld = True
    if withheld:
        cleaned["_withheld"] = True
    return cleaned


def _portable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _portable_mapping(value)
    if isinstance(value, (list, tuple)):
        items = tuple(_portable_value(item) for item in value)
        return [({"_withheld": True} if item is _OMIT else item)
                for item in items]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and _looks_like_sensitive_reference(value):
        return _OMIT
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _looks_like_sensitive_reference(value: str) -> bool:
    stripped = value.strip()
    scheme = urlsplit(stripped).scheme.lower()
    if scheme in _SENSITIVE_SCHEMES:
        return True
    if _CONNECTION_STRING.search(stripped):
        return True
    return (stripped.startswith(("/", "\\\\", "./", "../", "~/"))
            or bool(_WINDOWS_PATH.match(stripped)))


def _remove_storage_references(dataset: xr.Dataset) -> None:
    dataset.encoding = _portable_encoding(dataset.encoding)
    for variable in dataset.variables.values():
        variable.encoding = _portable_encoding(variable.encoding)


def _portable_encoding(encoding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in encoding.items()
        if not any(
            part in str(key).lower().replace("-", "_")
            for part in _STORAGE_ENCODING_KEY_PARTS
        )
        and not (
            isinstance(value, str) and _looks_like_sensitive_reference(value)
        )
    }


def _close_quietly(dataset: xr.Dataset) -> None:
    try:
        dataset.close()
    except Exception:
        pass


__all__ = ["CatalogueModelFieldQuery"]
