"""OPeNDAP source adapter.

Reaches model output published over OPeNDAP, which is how ocean modelling
centres serve their archives and how INCOIS already runs LAS/THREDDS.

The retrieval model differs from a download service: xarray opens the remote
dataset lazily, so selecting a subset transfers only that subset. Nothing is
written to disk unless the caller asks for it.

Datasets are named in configuration rather than discovered. A THREDDS
catalogue lists everything a centre publishes; this system wants the products
that answer the problem statement.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import xarray as xr

from ingestion.config import OpendapDataset, OpendapServer
from ingestion.domain.errors import SelectionError, SourceError
from ingestion.domain.selection import ImportSelection
from ingestion.ports import (
    DatasetMetadata, DatasetRef, FetchResult, RangeInfo, SourceCapabilities,
    SourceDescription, SourcePort, VariableInfo,
)

#: Coordinate names mapped onto the role each plays.
_ROLE_BY_NAME: dict[str, str] = {
    "time": "time",
    "depth": "vertical", "lev": "vertical", "z": "vertical",
    "lat": "latitude", "latitude": "latitude",
    "lon": "longitude", "longitude": "longitude",
}

#: Variables that describe the run rather than the ocean. HYCOM's `tau`
#: carries units of "hours since analysis", which is not a calendar and makes
#: xarray refuse to open the dataset at all if times are decoded eagerly.
_NOT_OCEAN_STATE = ("tau",)


class OpendapAdapter(SourcePort):
    """One OPeNDAP provider, exposed as a source."""

    def __init__(self, server: OpendapServer) -> None:
        self.server = server

    # -- identity -----------------------------------------------------------

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id=self.server.source_id,
            name=self.server.name,
            kind="remote",
            description=self.server.description,
            capabilities=SourceCapabilities(
                variable_selection=True, time_subsetting=True,
                depth_subsetting=True, spatial_subsetting=True),
        )

    def list_datasets(self, context: Optional[dict[str, Any]] = None
                      ) -> tuple[DatasetRef, ...]:
        return tuple(
            DatasetRef(dataset_id=entry.dataset_id, name=entry.name,
                       description=entry.description)
            for entry in self.server.datasets)

    def _entry(self, dataset_id: str) -> OpendapDataset:
        for entry in self.server.datasets:
            if entry.dataset_id == dataset_id:
                return entry
        raise SourceError(f"{dataset_id!r} is not offered by {self.server.name}")

    # -- opening ------------------------------------------------------------

    def _open(self, entry: OpendapDataset) -> xr.Dataset:
        """Open the remote dataset without transferring its values.

        Times are decoded afterwards rather than on open: a single variable
        with a non-calendar time unit would otherwise make the whole dataset
        unopenable.
        """
        try:
            return xr.open_dataset(entry.url, decode_times=False)
        except Exception as exc:
            raise SourceError(
                f"{self.server.name} could not be reached at "
                f"{entry.url}: {exc}") from exc

    # -- inspection ---------------------------------------------------------

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        entry = self._entry(dataset_id)
        dataset = self._open(entry)
        with dataset:
            variables = tuple(
                VariableInfo(
                    name=str(name),
                    units=variable.attrs.get("units"),
                    long_name=variable.attrs.get("long_name"),
                    standard_name=variable.attrs.get("standard_name"),
                    dimensions=tuple(str(d) for d in variable.dims))
                for name, variable in dataset.data_vars.items()
                if str(name) not in _NOT_OCEAN_STATE)

            ranges: list[RangeInfo] = []
            for name in dataset.coords:
                axis = dataset[name]
                if axis.ndim != 1 or not axis.size:
                    continue
                role = _ROLE_BY_NAME.get(str(name).lower(), str(name).lower())
                units = axis.attrs.get("units")
                if role == "time":
                    low = _as_instant(float(axis.values[0]), units)
                    high = _as_instant(float(axis.values[-1]), units)
                    units = "UTC"
                else:
                    low, high = _plain(axis.values[0]), _plain(axis.values[-1])
                ranges.append(RangeInfo(
                    dimension=str(name), role=role, minimum=low, maximum=high,
                    units=units, count=int(axis.size)))

            return DatasetMetadata(
                dataset_id=dataset_id, name=entry.name, variables=variables,
                ranges=tuple(ranges),
                attributes={k: str(v) for k, v in dataset.attrs.items()})

    # -- retrieval ----------------------------------------------------------

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        entry = self._entry(selection.dataset_id)
        dataset = self._open(entry)

        available = {str(n) for n in dataset.data_vars
                     if str(n) not in _NOT_OCEAN_STATE}
        chosen = list(dict.fromkeys(selection.variables)) or sorted(available)
        unknown = set(chosen) - available
        if unknown:
            dataset.close()
            raise SelectionError("this dataset has no variable(s) named "
                                 + ", ".join(sorted(unknown)))
        dataset = dataset[chosen]

        try:
            dataset, applied = _subset(dataset, selection)
            estimate = _values_in(dataset)
            if estimate > self.server.max_values_per_request:
                raise SelectionError(
                    f"that selection is about {estimate:,} values. Narrow the "
                    f"range or choose fewer variables to stay under "
                    f"{self.server.max_values_per_request:,}.")
            # Only now is anything transferred.
            dataset = dataset.load()
        except SelectionError:
            dataset.close()
            raise
        except Exception as exc:
            dataset.close()
            raise SourceError(
                f"{self.server.name} could not return that selection: "
                f"{exc}") from exc

        dataset = _decode_times(dataset)
        return FetchResult(
            dataset=dataset,
            location=entry.url,
            details={"provider": self.server.name,
                     "dataset_id": selection.dataset_id,
                     "url": entry.url,
                     "values_transferred": estimate,
                     "applied": applied},
        )


# -- selection ---------------------------------------------------------------

def _axis_names(dataset: xr.Dataset) -> dict[str, str]:
    return {_ROLE_BY_NAME.get(str(n).lower(), str(n).lower()): str(n)
            for n in dataset.coords if dataset[n].ndim == 1}


def _ordered(axis: xr.DataArray, low: Any, high: Any) -> slice:
    """A slice that respects the axis's stored direction."""
    values = axis.values
    if values.size > 1 and values[0] > values[-1]:
        return slice(high, low)
    return slice(low, high)


def _subset(dataset: xr.Dataset,
            selection: ImportSelection) -> tuple[xr.Dataset, dict[str, Any]]:
    roles = _axis_names(dataset)
    applied: dict[str, Any] = {}

    if selection.time and "time" in roles:
        name = roles["time"]
        units = dataset[name].attrs.get("units")
        low = _as_number(selection.time.start, units)
        high = _as_number(selection.time.end, units)
        dataset = dataset.sel({name: _ordered(dataset[name], low, high)})
        applied["time"] = [selection.time.start, selection.time.end]

    if selection.depth and "vertical" in roles:
        name = roles["vertical"]
        dataset = dataset.sel({name: _ordered(
            dataset[name], selection.depth.minimum, selection.depth.maximum)})
        applied["depth"] = [selection.depth.minimum, selection.depth.maximum]

    if selection.area:
        if "latitude" in roles:
            name = roles["latitude"]
            dataset = dataset.sel({name: _ordered(
                dataset[name], selection.area.south, selection.area.north)})
        if "longitude" in roles:
            name = roles["longitude"]
            west, east = _longitudes_for(dataset[roles["longitude"]],
                                         selection.area.west,
                                         selection.area.east)
            dataset = dataset.sel({name: _ordered(dataset[name], west, east)})
        applied["area"] = [selection.area.west, selection.area.east,
                           selection.area.south, selection.area.north]

    for role in ("time", "vertical", "latitude", "longitude"):
        name = roles.get(role)
        if name and dataset.sizes.get(name, 1) == 0:
            raise SelectionError(
                f"no {role} values fall inside the range you selected")
    return dataset, applied


def _longitudes_for(axis: xr.DataArray, west: float,
                    east: float) -> tuple[float, float]:
    """Express a requested longitude range in the axis's own convention.

    Models differ: some run 0 to 360, others -180 to 180. A request for -150
    means nothing on a 0-360 axis unless it is converted to 210 first.
    """
    low, high = float(axis.values.min()), float(axis.values.max())
    uses_360 = high > 180.0

    def convert(value: float) -> float:
        if uses_360 and value < 0:
            return value + 360.0
        if not uses_360 and value > 180:
            return value - 360.0
        return value

    west, east = convert(west), convert(east)
    if west > east:
        raise SelectionError(
            "an area crossing the edge of this model's longitude range is "
            f"not supported. Request it as two areas within {low} to {high}.")
    return west, east


def _values_in(dataset: xr.Dataset) -> int:
    """How many values the selection covers, before anything is transferred."""
    return int(sum(int(np.prod(v.shape)) for v in dataset.data_vars.values()))


# -- time --------------------------------------------------------------------

_SINCE = re.compile(r"\s*(\w+)\s+since\s+(.+)", re.IGNORECASE)
_SCALE = {"seconds": 1.0, "second": 1.0, "minutes": 60.0, "minute": 60.0,
          "hours": 3600.0, "hour": 3600.0, "days": 86400.0, "day": 86400.0}


def _origin(units: Optional[str]) -> Optional[tuple[datetime, float]]:
    match = _SINCE.match(units or "")
    if not match:
        return None
    scale = _SCALE.get(match.group(1).lower())
    if scale is None:
        return None
    try:
        moment = datetime.fromisoformat(
            match.group(2).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment, scale


def _as_instant(value: float, units: Optional[str]) -> Any:
    """A CF time value rendered as an ISO instant."""
    resolved = _origin(units)
    if resolved is None:
        return value
    origin, scale = resolved
    return (origin + timedelta(seconds=value * scale)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _as_number(text: str, units: Optional[str]) -> Any:
    """An ISO instant expressed in the axis's own numbering."""
    resolved = _origin(units)
    if resolved is None:
        return text
    origin, scale = resolved
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SelectionError(f"{text!r} is not a valid date") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - origin).total_seconds() / scale


def _decode_times(dataset: xr.Dataset) -> xr.Dataset:
    """Turn the numeric time axis into real datetimes, once values are here.

    Done after transfer and only for the time coordinate, so a variable with
    a non-calendar time unit cannot make the dataset unopenable.
    """
    if "time" not in dataset.coords:
        return dataset
    resolved = _origin(dataset["time"].attrs.get("units"))
    if resolved is None:
        return dataset
    origin, scale = resolved
    attrs = dict(dataset["time"].attrs)
    stamps = [np.datetime64(
        (origin + timedelta(seconds=float(v) * scale)).replace(tzinfo=None), "ns")
        for v in np.atleast_1d(dataset["time"].values)]
    decoded = dataset.assign_coords(time=np.array(stamps, dtype="datetime64[ns]"))
    # `units` and `calendar` described the numbering that has just been
    # decoded away. Left on the variable they collide with the encoding a
    # writer sets for a real datetime, and the dataset cannot be saved.
    for key in ("units", "calendar", "_FillValue", "missing_value"):
        attrs.pop(key, None)
    decoded["time"].attrs = attrs
    decoded["time"].encoding = {}
    return decoded


def _plain(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value
