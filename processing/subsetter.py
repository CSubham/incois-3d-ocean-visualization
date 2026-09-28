"""Pure, exact-index subsetting for decoded rectilinear scalar grids."""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from processing.domain import (
    CoordinateMetadata, ProductIdentity, ScalarGridDescriptor,
    ScalarSelection, ScalarSubset,
)
from processing.errors import (
    EmptySubsetError, GridValidationError, TimeSelectionError,
    VariableSelectionError, WorkLimitError,
)


def _coordinate(dataset: xr.Dataset, name: str, role: str) -> xr.DataArray:
    if name not in dataset.coords:
        raise GridValidationError(
            f"{role} coordinate {name!r} is absent from dataset coordinates")
    coordinate = dataset.coords[name]
    if coordinate.ndim != 1 or len(coordinate.dims) != 1:
        raise GridValidationError(
            f"{role} coordinate {name!r} must be one-dimensional for a "
            "rectilinear grid")
    if coordinate.size == 0:
        raise GridValidationError(f"{role} coordinate {name!r} is empty")
    if bool(np.asarray(coordinate.isnull().values).any()):
        raise GridValidationError(
            f"{role} coordinate {name!r} contains missing values")
    return coordinate


def _numeric_spatial_values(coordinate: xr.DataArray,
                            role: str) -> np.ndarray:
    values = np.asarray(coordinate.values)
    if (not np.issubdtype(values.dtype, np.number)
            or np.issubdtype(values.dtype, np.complexfloating)
            or np.issubdtype(values.dtype, np.bool_)):
        raise GridValidationError(
            f"{role} coordinate {coordinate.name!r} must contain real numbers")
    if not bool(np.isfinite(values).all()):
        raise GridValidationError(
            f"{role} coordinate {coordinate.name!r} must contain finite values")
    return values


def _declared(coordinate: xr.DataArray, name: str) -> str | None:
    """A source-declared attribute, wherever CF decoding left it.

    Decoding moves ``units`` and ``calendar`` of a time coordinate from its
    attributes into its encoding.
    """
    value = coordinate.attrs.get(name, coordinate.encoding.get(name))
    return None if value is None else str(value)


def _time_indices(values: np.ndarray, requested: Any) -> np.ndarray:
    target = requested
    if np.issubdtype(values.dtype, np.datetime64):
        try:
            target = np.asarray(requested, dtype=values.dtype)
        except (TypeError, ValueError, OverflowError):
            return np.array([], dtype=np.intp)
    try:
        matches = np.asarray(values == target, dtype=bool)
    except (TypeError, ValueError):
        return np.array([], dtype=np.intp)
    return np.flatnonzero(matches)


def _bounded_indices(values: np.ndarray, minimum: float, maximum: float,
                     role: str, coordinate_name: str) -> np.ndarray:
    selected = np.flatnonzero((values >= minimum) & (values <= maximum))
    if selected.size == 0:
        available_min = np.min(values).item()
        available_max = np.max(values).item()
        raise EmptySubsetError(
            f"{role} bounds [{minimum}, {maximum}] select no cells from "
            f"coordinate {coordinate_name!r}; available extent is "
            f"[{available_min}, {available_max}]")
    return selected


def subset_scalar_field(dataset: xr.Dataset,
                        descriptor: ScalarGridDescriptor,
                        selection: ScalarSelection,
                        maximum_cells: int | None = None) -> ScalarSubset:
    """Select a source-exact 3D scalar subset without modifying ``dataset``.

    ``maximum_cells`` is checked from the coordinates alone, before any value
    is read, so an oversized selection costs nothing to refuse.
    """
    if not isinstance(dataset, xr.Dataset):
        raise GridValidationError("decoded input must be an xarray.Dataset")

    roles = descriptor.coordinates
    time = _coordinate(dataset, roles.time, "time")
    depth = _coordinate(dataset, roles.depth, "depth")
    latitude = _coordinate(dataset, roles.latitude, "latitude")
    longitude = _coordinate(dataset, roles.longitude, "longitude")

    coordinate_dimensions = {
        "time": time.dims[0],
        "depth": depth.dims[0],
        "latitude": latitude.dims[0],
        "longitude": longitude.dims[0],
    }
    if len(set(coordinate_dimensions.values())) != 4:
        raise GridValidationError(
            "time, depth, latitude and longitude must span distinct dimensions "
            "for an unambiguous rectilinear grid")

    declared_positive = descriptor.spatial_reference.vertical_positive
    source_positive = depth.attrs.get("positive")
    if (source_positive is not None
            and str(source_positive).strip().lower() != declared_positive):
        raise GridValidationError(
            f"depth coordinate {roles.depth!r} declares positive "
            f"{source_positive!r}, contradicting the declared vertical "
            f"direction {declared_positive!r}")

    depth_values = _numeric_spatial_values(depth, "depth")
    latitude_values = _numeric_spatial_values(latitude, "latitude")
    longitude_values = _numeric_spatial_values(longitude, "longitude")

    variable_name = selection.variable
    if variable_name not in dataset.data_vars:
        available = ", ".join(sorted(str(name)
                                     for name in dataset.data_vars)) or "none"
        if variable_name in dataset.variables:
            detail = "it is a coordinate or ancillary variable"
        else:
            detail = "it is absent"
        raise VariableSelectionError(
            f"scalar variable {variable_name!r} cannot be selected because "
            f"{detail}; available data variables: {available}")
    variable = dataset[variable_name]
    expected_dimensions = set(coordinate_dimensions.values())
    if (variable.ndim != 4 or len(set(variable.dims)) != 4
            or set(variable.dims) != expected_dimensions):
        raise GridValidationError(
            f"scalar variable {variable_name!r} must use exactly the time, "
            "depth, latitude and longitude dimensions of the declared "
            f"rectilinear grid; found dimensions {variable.dims!r}")
    if (not np.issubdtype(variable.dtype, np.number)
            or np.issubdtype(variable.dtype, np.complexfloating)
            or np.issubdtype(variable.dtype, np.bool_)):
        raise VariableSelectionError(
            f"scalar variable {variable_name!r} must contain real numeric "
            f"values, not dtype {variable.dtype}")
    units = variable.attrs.get("units")
    if not isinstance(units, str) or not units.strip():
        raise VariableSelectionError(
            f"scalar variable {variable_name!r} has no declared units")

    time_values = np.asarray(time.values)
    matching_times = _time_indices(time_values, selection.time)
    if matching_times.size == 0:
        raise TimeSelectionError(
            f"requested time {selection.time!r} is unavailable on coordinate "
            f"{roles.time!r}")
    if matching_times.size != 1:
        raise TimeSelectionError(
            f"requested time {selection.time!r} matches {matching_times.size} "
            "source cells; the time coordinate must identify exactly one")
    time_index = int(matching_times[0])

    depth_indices = _bounded_indices(
        depth_values, selection.depth.minimum, selection.depth.maximum,
        "depth", roles.depth)
    latitude_indices = _bounded_indices(
        latitude_values, selection.area.south, selection.area.north,
        "latitude", roles.latitude)
    longitude_indices = _bounded_indices(
        longitude_values, selection.area.west, selection.area.east,
        "longitude", roles.longitude)

    cells = depth_indices.size * latitude_indices.size * longitude_indices.size
    if maximum_cells is not None and cells > maximum_cells:
        raise WorkLimitError(
            f"the selection covers {cells} cells ({depth_indices.size} depth "
            f"x {latitude_indices.size} latitude x {longitude_indices.size} "
            f"longitude); this server builds at most {maximum_cells}. Narrow "
            "the area or depth range")

    ordered = variable.isel({
        coordinate_dimensions["time"]: time_index,
        coordinate_dimensions["depth"]: depth_indices,
        coordinate_dimensions["latitude"]: latitude_indices,
        coordinate_dimensions["longitude"]: longitude_indices,
    }).transpose(coordinate_dimensions["depth"],
                 coordinate_dimensions["latitude"],
                 coordinate_dimensions["longitude"])

    raw_values = np.asanyarray(ordered.values)
    values = np.array(np.ma.getdata(raw_values), copy=True)
    missing_mask = np.asarray(np.ma.getmaskarray(raw_values), dtype=bool)
    missing_mask |= np.asarray(ordered.isnull().values, dtype=bool)

    selected_time = np.asarray(time_values[time_index]).copy()[()]
    coordinates = {"time": time, "depth": depth,
                   "latitude": latitude, "longitude": longitude}
    coordinate_units = {role: _declared(coordinate, "units")
                        for role, coordinate in coordinates.items()}
    return ScalarSubset(
        identity=ProductIdentity(
            dataset_id=descriptor.identity.dataset_id,
            dataset_version_id=descriptor.identity.dataset_version_id,
            variable=variable_name,
            time_coordinate=roles.time,
            time_value=selected_time,
        ),
        coordinates=CoordinateMetadata(
            names=roles,
            dimensions=coordinate_dimensions,
            units=coordinate_units,
            dtypes={role: str(coordinate.dtype)
                    for role, coordinate in coordinates.items()},
            time_encoding={"units": _declared(time, "units"),
                           "calendar": _declared(time, "calendar")},
        ),
        spatial_reference=descriptor.spatial_reference,
        source_dimensions=tuple(str(dim) for dim in variable.dims),
        semantic_dimensions=(coordinate_dimensions["depth"],
                             coordinate_dimensions["latitude"],
                             coordinate_dimensions["longitude"]),
        variable_units=units,
        provenance=descriptor.provenance,
        time_source_index=time_index,
        depth_source_indices=tuple(int(index) for index in depth_indices),
        latitude_source_indices=tuple(int(index)
                                      for index in latitude_indices),
        longitude_source_indices=tuple(int(index)
                                       for index in longitude_indices),
        depth_values=depth_values[depth_indices],
        latitude_values=latitude_values[latitude_indices],
        longitude_values=longitude_values[longitude_indices],
        values=values,
        missing_value_mask=missing_mask,
    )
