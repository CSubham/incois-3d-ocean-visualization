"""PostgreSQL catalogue and ObjectStore model-field query adapter."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

import psycopg
import xarray as xr
from psycopg.rows import dict_row

from ingestion.query import (
    DatasetExtent, DatasetVersionSummary, ManagedModelField,
    ModelFieldDescriptor, ModelFieldQuery, ModelFieldQueryError,
    NotAModelField, UndeclaredReference, VariableSummary,
    VariableUnavailable, VersionNotFound,
)
from ingestion.storage.objects import ObjectStore


_VERSION_COLUMNS = """
    import_id, source_id, source_name, dataset_id, dataset_name,
    source_kind, geometry, object_ref, sizes, selection, validation,
    metadata, source_details, time_start, time_end, depth_min, depth_max,
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

_REQUIRED_COORDINATES = ("time", "vertical", "latitude", "longitude")
_SENSITIVE_KEY_PARTS = (
    "path", "object", "dsn", "connection", "cursor", "sql", "bucket",
    "container", "credential", "password", "secret", "token",
)
_STORAGE_ENCODING_KEY_PARTS = (
    "source", "path", "filename", "object", "dsn", "bucket", "container",
)
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_OMIT = object()


class CatalogueModelFieldQuery(ModelFieldQuery):
    """Read managed model fields without leaking catalogue/store details."""

    def __init__(
        self,
        catalogue_dsn: str,
        objects: ObjectStore,
        source_references: Mapping[str, Any],
        *,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self._catalogue_dsn = catalogue_dsn
        self._objects = objects
        self._source_references = dict(source_references)
        self._connect = connect

    def list_model_versions(self) -> tuple[DatasetVersionSummary, ...]:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(_LIST_VERSIONS_SQL, ("grid",))
                    versions = tuple(cursor.fetchall())
                    variables = self._variables(cursor, [
                        str(row["import_id"]) for row in versions
                    ])
            return tuple(
                _summary(row, variables[str(row["import_id"])])
                for row in versions
            )
        except ModelFieldQueryError:
            raise
        except Exception:
            raise ModelFieldQueryError(
                "the model-field catalogue could not be read") from None

    def describe_version(
            self, dataset_version_id: str) -> DatasetVersionSummary:
        version, variables = self._version(dataset_version_id)
        _require_grid(version)
        return _summary(version, variables)

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
        return psycopg.connect(self._catalogue_dsn, row_factory=dict_row)


def _require_grid(version: Mapping[str, Any]) -> None:
    geometry = str(version.get("geometry", ""))
    if geometry != "grid":
        raise NotAModelField(str(version["import_id"]), geometry)


def _summary(version: Mapping[str, Any],
             variables: Sequence[Mapping[str, Any]]) -> DatasetVersionSummary:
    version_id = str(version["import_id"])
    coordinate_names = _coordinate_names(version, version_id)
    sizes = _required_mapping(version, "sizes", version_id)
    try:
        depth_levels = int(sizes[coordinate_names["vertical"]])
        time_steps = int(sizes[coordinate_names["time"]])
    except (KeyError, TypeError, ValueError):
        raise UndeclaredReference(
            version_id, "time and depth coordinate dimensions") from None
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
        extent=DatasetExtent(
            time_start=_iso(version.get("time_start")),
            time_end=_iso(version.get("time_end")),
            depth_min=_optional_float(version.get("depth_min")),
            depth_max=_optional_float(version.get("depth_max")),
            west=_optional_float(version.get("west")),
            east=_optional_float(version.get("east")),
            south=_optional_float(version.get("south")),
            north=_optional_float(version.get("north")),
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

    metadata = _required_mapping(version, "metadata", version_id)
    source_details = _required_mapping(version, "source_details", version_id)
    provenance = {
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
        "reference_basis": {
            "crs": crs_basis,
            "vertical_positive": vertical_basis,
        },
        "global_attributes": _portable_mapping(
            _mapping(metadata.get("global_attributes", {}),
                     version_id, "global attributes")),
    }
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


def _portable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        normalized = name.lower().replace("-", "_")
        if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
            continue
        portable = _portable_value(item)
        if portable is not _OMIT:
            cleaned[name] = portable
    return cleaned


def _portable_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _portable_mapping(value)
    if isinstance(value, (list, tuple)):
        items = tuple(_portable_value(item) for item in value)
        return [item for item in items if item is not _OMIT]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and _looks_like_filesystem_path(value):
        return _OMIT
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _looks_like_filesystem_path(value: str) -> bool:
    if "://" in value:
        return False
    return (value.startswith(("/", "\\\\"))
            or bool(_WINDOWS_PATH.match(value))
            or "/" in value or "\\" in value)


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
            isinstance(value, str) and _looks_like_filesystem_path(value)
        )
    }


def _close_quietly(dataset: xr.Dataset) -> None:
    try:
        dataset.close()
    except Exception:
        pass


__all__ = ["CatalogueModelFieldQuery"]
