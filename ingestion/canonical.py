"""Turn retrieved data into the canonical representation.

Two jobs: work out which coordinate plays which scientific role, and classify
what shape the dataset actually is. Neither renames the source's variables --
normalizing metadata must not destroy the structure the data arrived in.
"""

from __future__ import annotations

from typing import Any, Optional

import cf_xarray  # noqa: F401  -- registers the .cf accessor
import numpy as np
import xarray as xr

from ingestion.domain.errors import ConventionError
from ingestion.domain.package import (
    CoordinateSet, DatasetGeometry, VariableSpec,
)

#: Fallback coordinate names, tried only where cf-xarray cannot identify a
#: role from the dataset's own attributes.
FALLBACK_NAMES: dict[str, tuple[str, ...]] = {
    "time": ("time", "TIME", "date", "datetime", "juld", "JULD"),
    "vertical": ("depth", "DEPTH", "ZAX", "z", "lev", "level",
                 "pressure", "pres", "PRES", "dbar"),
    "latitude": ("lat", "latitude", "LATITUDE", "LAT", "y"),
    "longitude": ("lon", "longitude", "LONGITUDE", "LON", "x"),
}

#: A grouping identifier makes a set of measurements a collection of profiles.
PROFILE_HINTS: tuple[str, ...] = (
    "profile", "platform", "station", "cast", "float", "wmo",
)
#: A trajectory identifier means the platform moved while measuring.
TRAJECTORY_HINTS: tuple[str, ...] = ("trajectory", "glider", "track")

#: CF Discrete Sampling Geometries name the shape outright. When a dataset
#: declares one, it is taken at its word rather than inferred from structure.
FEATURE_TYPES: dict[str, str] = {
    "point": "POINT", "timeseries": "POINT",
    "trajectory": "TRAJECTORY", "profile": "PROFILE",
    "timeseriesprofile": "PROFILE", "trajectoryprofile": "TRAJECTORY_PROFILE",
}

_CF_ROLES = {"time": ("T", "time"), "vertical": ("Z", "vertical"),
             "latitude": ("Y", "latitude"), "longitude": ("X", "longitude")}


def _cf_lookup(dataset: xr.Dataset, role: str) -> Optional[str]:
    for key in _CF_ROLES[role]:
        try:
            found = dataset.cf.axes.get(key) or dataset.cf.coordinates.get(key)
        except Exception:
            found = None
        if found:
            return str(found[0])
    return None


def identify_coordinates(dataset: xr.Dataset) -> CoordinateSet:
    """Map scientific roles onto the dataset's own coordinate names.

    cf-xarray first, so a CF-compliant source needs no name knowledge at all.
    The fallback list covers sources that omit the attributes.
    """
    resolved: dict[str, Optional[str]] = {}
    known = set(dataset.variables)
    for role, candidates in FALLBACK_NAMES.items():
        name = _cf_lookup(dataset, role)
        if name is None:
            name = next((c for c in candidates if c in known), None)
        resolved[role] = name
    return CoordinateSet(**resolved)


def _varies(dataset: xr.Dataset, name: str) -> bool:
    """True when a coordinate takes more than one distinct value."""
    try:
        values = np.asarray(dataset[name].values).ravel()
        finite = values[~np.isnan(values)] if values.dtype.kind == "f" else values
        return finite.size > 0 and np.unique(finite).size > 1
    except Exception:
        return False


def _has_marker(dataset: xr.Dataset, sample_dim: str,
                hints: tuple[str, ...]) -> bool:
    for name, variable in dataset.variables.items():
        if variable.dims != (sample_dim,):
            continue
        if any(hint in str(name).lower() for hint in hints):
            return True
    return False


def classify_geometry(dataset: xr.Dataset,
                      coordinates: CoordinateSet) -> DatasetGeometry:
    """Decide what shape this dataset is.

    Raises rather than guessing: an unclassifiable dataset is reported, never
    forced into the nearest-looking category.
    """
    declared = str(dataset.attrs.get("featureType", "")).strip().lower()
    if declared:
        named = FEATURE_TYPES.get(declared.replace("_", "").replace("-", ""))
        if named:
            return DatasetGeometry[named]
        raise ConventionError(
            f"the dataset declares featureType {declared!r}, which is not a "
            "shape this application supports")

    latitude, longitude = coordinates.latitude, coordinates.longitude
    if not latitude or not longitude:
        raise ConventionError(
            "latitude and longitude could not be identified, so the shape of "
            "the data cannot be determined")

    lat_dims = dataset[latitude].dims
    lon_dims = dataset[longitude].dims
    vertical = coordinates.vertical

    # Gridded: latitude and longitude each span their own axis.
    if len(lat_dims) == 1 and len(lon_dims) == 1 and lat_dims != lon_dims:
        return DatasetGeometry.GRID

    if lat_dims != lon_dims:
        raise ConventionError(
            f"latitude ({latitude}) and longitude ({longitude}) vary over "
            "different dimensions, which matches no supported dataset shape")
    if len(lat_dims) != 1:
        raise ConventionError(
            "latitude and longitude do not vary over a single sampling "
            "dimension, so the dataset shape is ambiguous")

    sample_dim = lat_dims[0]
    moving = _varies(dataset, latitude) or _varies(dataset, longitude)
    has_vertical = bool(vertical)

    if not has_vertical:
        return DatasetGeometry.TRAJECTORY if moving else DatasetGeometry.POINT

    # A grouping identifier is what makes measurements a set of profiles; with
    # depth on its own axis the positions are per-profile by construction.
    if _has_marker(dataset, sample_dim, TRAJECTORY_HINTS):
        return DatasetGeometry.TRAJECTORY_PROFILE
    if _has_marker(dataset, sample_dim, PROFILE_HINTS) or not moving:
        return DatasetGeometry.PROFILE
    return DatasetGeometry.TRAJECTORY_PROFILE


def _fill_value(variable: xr.DataArray) -> Any:
    for key in ("_FillValue", "missing_value"):
        if key in variable.encoding:
            return _plain(variable.encoding[key])
        if key in variable.attrs:
            return _plain(variable.attrs[key])
    return None


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return value


#: Name markers for quality flags, which are not measured quantities.
_FLAG_MARKERS = ("_qc", "_flag", "qartod", "_quality")


def ancillary_names(dataset: xr.Dataset) -> set[str]:
    """Variables that describe other variables rather than measure anything.

    CF marks these explicitly -- quality flags, grid-mapping and geometry
    containers, and anything another variable names as ancillary. They are
    preserved in the dataset but are not offered or checked as scientific
    variables, because they legitimately carry no units.
    """
    names: set[str] = set()
    for name, variable in dataset.variables.items():
        lowered = str(name).lower()
        if any(marker in lowered for marker in _FLAG_MARKERS):
            names.add(str(name))
        # Text is a label, never a measurement.
        if variable.dtype.kind in "OUS":
            names.add(str(name))
        # CF containers carry attributes rather than data.
        if variable.ndim == 0:
            names.add(str(name))
        if "flag_values" in variable.attrs or "flag_meanings" in variable.attrs:
            names.add(str(name))
        for attribute in ("ancillary_variables", "grid_mapping", "geometry",
                          "bounds", "climatology", "nodes"):
            referenced = variable.attrs.get(attribute)
            if isinstance(referenced, str):
                names.update(referenced.split())
    return names


def describe_variables(dataset: xr.Dataset,
                       coordinates: CoordinateSet) -> tuple[VariableSpec, ...]:
    """Record each imported variable, preserving the source's own metadata.

    Ancillary variables are excluded from the scientific set but left in the
    dataset, so nothing the source supplied is discarded.
    """
    roles = set(coordinates.identified().values())
    ancillary = ancillary_names(dataset)
    specs: list[VariableSpec] = []
    for name, variable in dataset.data_vars.items():
        if str(name) in roles or str(name) in ancillary:
            continue
        specs.append(VariableSpec(
            name=str(name),
            original_name=str(variable.attrs.get("original_name", name)),
            units=variable.attrs.get("units"),
            standard_name=variable.attrs.get("standard_name"),
            long_name=variable.attrs.get("long_name"),
            dimensions=tuple(str(d) for d in variable.dims),
            fill_value=_fill_value(variable),
        ))
    return tuple(specs)


def collect_metadata(dataset: xr.Dataset,
                     coordinates: CoordinateSet) -> dict[str, Any]:
    """Metadata worth carrying past this stage, normalized but not rewritten."""
    coordinate_units = {
        role: dataset[name].attrs.get("units")
        for role, name in coordinates.identified().items() if name in dataset
    }
    return {
        "global_attributes": {k: _plain(v) for k, v in dataset.attrs.items()},
        "coordinate_names": coordinates.identified(),
        "coordinate_units": coordinate_units,
        "dimensions": {str(k): int(v) for k, v in dataset.sizes.items()},
    }
