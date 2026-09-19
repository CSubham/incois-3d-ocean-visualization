"""Local NetCDF source adapter.

Reads NetCDF files the user has chosen from a configured location. CF-aware
decoding is applied on read, so packed values, times and fill values arrive
already resolved.
"""

from __future__ import annotations

from typing import Any, Optional

import xarray as xr

from ingestion.config import NETCDF_SUFFIXES
from ingestion.domain.errors import SelectionError, SourceError
from ingestion.domain.selection import ImportSelection
from ingestion.adapters.local_base import LocalSourceAdapter
from ingestion.ports import (
    DatasetMetadata, FetchResult, RangeInfo, SourceCapabilities,
    SourceDescription, VariableInfo,
)

SOURCE_ID = "local_netcdf"

_ROLE_HINTS = {
    "time": ("time", "date", "juld"),
    "vertical": ("depth", "zax", "lev", "pres", "z"),
    "latitude": ("lat",),
    "longitude": ("lon",),
}


def _role_of(name: str) -> str:
    lowered = name.lower()
    for role, hints in _ROLE_HINTS.items():
        if any(hint in lowered for hint in hints):
            return role
    return lowered


class LocalNetcdfAdapter(LocalSourceAdapter):
    suffixes = NETCDF_SUFFIXES

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id=SOURCE_ID,
            name="NetCDF file",
            kind="local",
            description="A NetCDF file you choose.",
            capabilities=SourceCapabilities(
                variable_selection=True, time_subsetting=True,
                depth_subsetting=True, spatial_subsetting=True),
            requires_user_files=True,
        )

    def _open(self, dataset_id: str) -> tuple[xr.Dataset, Any]:
        path = self.resolve(dataset_id)
        try:
            return xr.open_dataset(path, decode_cf=True, mask_and_scale=True,
                                   decode_times=True), path
        except Exception as exc:
            raise SourceError(f"{path.name} could not be read: {exc}") from exc

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        dataset, path = self._open(dataset_id)
        with dataset:
            variables = tuple(
                VariableInfo(
                    name=str(name),
                    units=variable.attrs.get("units"),
                    long_name=variable.attrs.get("long_name"),
                    standard_name=variable.attrs.get("standard_name"),
                    dimensions=tuple(str(d) for d in variable.dims),
                )
                for name, variable in dataset.data_vars.items())
            ranges = tuple(
                RangeInfo(
                    dimension=str(name), role=_role_of(str(name)),
                    minimum=_edge(dataset[name], 0),
                    maximum=_edge(dataset[name], -1),
                    units=dataset[name].attrs.get("units"),
                    count=int(dataset[name].size))
                for name in dataset.coords
                if dataset[name].ndim == 1 and dataset[name].size)
            return DatasetMetadata(
                dataset_id=dataset_id, name=path.name, variables=variables,
                ranges=ranges,
                attributes={k: str(v) for k, v in dataset.attrs.items()})

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        dataset, path = self._open(selection.dataset_id)
        if selection.variables:
            unknown = set(selection.variables) - set(map(str, dataset.data_vars))
            if unknown:
                dataset.close()
                raise SelectionError(
                    "this file has no variable(s) named "
                    + ", ".join(sorted(unknown)))
            dataset = dataset[list(selection.variables)]
        dataset = _subset(dataset, selection)
        return FetchResult(
            dataset=dataset, location=str(path),
            details={"file": path.name, "file_size_bytes": path.stat().st_size},
        )


def _edge(array: xr.DataArray, index: int) -> Any:
    """One end of a coordinate, rendered so a person can read it."""
    import numpy as np
    value = array.values[index]
    if np.issubdtype(array.dtype, np.datetime64):
        return str(np.datetime_as_string(value, unit="s")) + "Z"
    return value.item() if hasattr(value, "item") else value


def _slice_for(array: xr.DataArray, low: Any, high: Any) -> slice:
    """Respect the stored direction of a coordinate."""
    values = array.values
    if values.size > 1 and values[0] > values[-1]:
        return slice(high, low)
    return slice(low, high)


def _subset(dataset: xr.Dataset, selection: ImportSelection) -> xr.Dataset:
    roles = {_role_of(str(name)): str(name) for name in dataset.coords
             if dataset[name].ndim == 1}
    if selection.time and "time" in roles:
        name = roles["time"]
        dataset = dataset.sel({name: slice(selection.time.start,
                                           selection.time.end)})
    if selection.depth and "vertical" in roles:
        name = roles["vertical"]
        dataset = dataset.sel({name: _slice_for(
            dataset[name], selection.depth.minimum, selection.depth.maximum)})
    if selection.area:
        if "latitude" in roles:
            name = roles["latitude"]
            dataset = dataset.sel({name: _slice_for(
                dataset[name], selection.area.south, selection.area.north)})
        if "longitude" in roles:
            name = roles["longitude"]
            dataset = dataset.sel({name: _slice_for(
                dataset[name], selection.area.west, selection.area.east)})
    return dataset
