"""Local delimited-text source adapter.

Reads CSV and similar observation files. Units are never inferred from column
names: they come from a sidecar description beside the file, or from a units
row the file itself carries. A file offering neither is reported as missing
units rather than guessed at.

Identifier and quality-flag columns are kept as ancillary coordinates rather
than treated as measured quantities, which preserves them without asserting
that they are scientific variables.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import xarray as xr

from ingestion.config import DELIMITED_SUFFIXES
from ingestion.domain.errors import SelectionError, SourceError
from ingestion.domain.selection import ImportSelection
from ingestion.adapters.local_base import LocalSourceAdapter
from ingestion.ports import (
    DatasetMetadata, FetchResult, RangeInfo, SourceCapabilities,
    SourceDescription, VariableInfo,
)

SOURCE_ID = "local_delimited"
OBSERVATION_DIM = "observation"

_ROLE_COLUMNS = {
    "time": ("time", "date", "datetime", "juld"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon"),
    "vertical": ("pres", "pressure", "depth", "dbar", "z"),
}
_FLAG_MARKERS = ("_qc", "_flag", "qartod", "_quality")
_IDENTIFIER_MARKERS = ("platform", "cycle", "station", "profile", "float",
                       "wmo", "trajectory", "cast", "_id")


def _role_of(column: str) -> Optional[str]:
    lowered = column.lower()
    for role, names in _ROLE_COLUMNS.items():
        if lowered in names or any(lowered.startswith(n) for n in names):
            return role
    return None


def _is_ancillary(column: str) -> bool:
    lowered = column.lower()
    return (any(marker in lowered for marker in _FLAG_MARKERS)
            or any(marker in lowered for marker in _IDENTIFIER_MARKERS))


def _delimiter(path: Path) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    sample = path.read_text(errors="replace")[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _declared_units(path: Path, columns: list[str],
                    second_row: list[str]) -> dict[str, str]:
    """Units as the file or its sidecar declares them. Never inferred."""
    sidecar = path.with_suffix(".json")
    if sidecar.exists():
        try:
            described = json.loads(sidecar.read_text())
            names = described.get("columns")
            units = described.get("column_units")
            if isinstance(names, list) and isinstance(units, list):
                return {str(n): str(u) for n, u in zip(names, units) if u}
        except (json.JSONDecodeError, OSError):
            pass  # a malformed sidecar is not authority; fall through
    # An ERDDAP-style units row: the second line describes rather than counts.
    if second_row and len(second_row) == len(columns):
        numeric = sum(1 for cell in second_row if _looks_numeric(cell))
        if numeric == 0:
            return {name: cell for name, cell in zip(columns, second_row)
                    if cell.strip()}
    return {}


def _looks_numeric(cell: str) -> bool:
    try:
        float(cell)
        return True
    except (TypeError, ValueError):
        return False


def _read(path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    delimiter = _delimiter(path)
    with open(path, newline="", errors="replace") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise SourceError(f"{path.name} is empty") from exc
        second = next(reader, [])
    units = _declared_units(path, columns, second)
    skip = [1] if units and second and not any(
        _looks_numeric(cell) for cell in second) else None
    try:
        frame = pd.read_csv(path, delimiter=delimiter, skiprows=skip)
    except Exception as exc:
        raise SourceError(f"{path.name} could not be read: {exc}") from exc
    if frame.empty:
        raise SourceError(f"{path.name} contains no rows")
    return frame, units


def _to_dataset(frame: pd.DataFrame, units: dict[str, str]) -> xr.Dataset:
    """Build an observation-dimensioned dataset, preserving row structure."""
    coords: dict[str, Any] = {}
    data: dict[str, Any] = {}
    for column in frame.columns:
        series = frame[column]
        values = series.to_numpy()
        attrs = {"units": units[column]} if column in units else {}
        role = _role_of(str(column))
        if role == "time":
            values = pd.to_datetime(series, errors="coerce",
                                    format="mixed", utc=True).to_numpy()
            attrs.pop("units", None)
        if role or _is_ancillary(str(column)):
            coords[str(column)] = ((OBSERVATION_DIM,), values, attrs)
        else:
            if values.dtype == object:
                values = pd.to_numeric(series, errors="coerce").to_numpy()
            data[str(column)] = ((OBSERVATION_DIM,), values, attrs)
    return xr.Dataset(data_vars=data, coords=coords)


class LocalDelimitedAdapter(LocalSourceAdapter):
    suffixes = DELIMITED_SUFFIXES

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id=SOURCE_ID,
            name="Text or CSV file",
            kind="local",
            description="A delimited observation file you choose.",
            capabilities=SourceCapabilities(
                variable_selection=True, time_subsetting=True,
                depth_subsetting=True, spatial_subsetting=True),
            requires_user_files=True,
        )

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        path = self.resolve(dataset_id)
        frame, units = _read(path)
        dataset = _to_dataset(frame, units)
        notes: list[str] = []
        if not units:
            notes.append("This file declares no units for its columns.")
        variables = tuple(
            VariableInfo(name=str(name),
                         units=variable.attrs.get("units"),
                         dimensions=(OBSERVATION_DIM,))
            for name, variable in dataset.data_vars.items())
        ranges = tuple(
            RangeInfo(dimension=str(name), role=_role_of(str(name)) or "other",
                      minimum=_edge(dataset[name], "min"),
                      maximum=_edge(dataset[name], "max"),
                      units=dataset[name].attrs.get("units"),
                      count=int(dataset[name].size))
            for name in dataset.coords if _role_of(str(name)))
        return DatasetMetadata(
            dataset_id=dataset_id, name=path.name, variables=variables,
            ranges=ranges, attributes={"rows": str(len(frame))},
            notes=tuple(notes))

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        path = self.resolve(selection.dataset_id)
        frame, units = _read(path)
        dataset = _to_dataset(frame, units)
        if selection.variables:
            unknown = set(selection.variables) - set(map(str, dataset.data_vars))
            if unknown:
                raise SelectionError("this file has no column(s) named "
                                     + ", ".join(sorted(unknown)))
            dataset = dataset[list(selection.variables)]
        dataset = _filter(dataset, selection)
        if dataset.sizes.get(OBSERVATION_DIM, 0) == 0:
            raise SelectionError(
                "no rows fall inside the range you selected")
        return FetchResult(
            dataset=dataset, location=str(path),
            details={"file": path.name, "rows": int(len(frame)),
                     "file_size_bytes": path.stat().st_size})


def _edge(array: xr.DataArray, which: str) -> Any:
    """One end of a column, rendered so a person can read it."""
    try:
        value = array.min().values if which == "min" else array.max().values
        if np.issubdtype(array.dtype, np.datetime64):
            return str(np.datetime_as_string(value, unit="s")) + "Z"
        return value.item() if hasattr(value, "item") else value
    except Exception:
        return None


def _filter(dataset: xr.Dataset, selection: ImportSelection) -> xr.Dataset:
    """Select rows by range. Rows, not axes -- this data is not gridded."""
    roles = {_role_of(str(name)): str(name) for name in dataset.coords
             if _role_of(str(name))}
    keep = np.ones(dataset.sizes.get(OBSERVATION_DIM, 0), dtype=bool)

    def within(name: str, low: Any, high: Any) -> np.ndarray:
        values = dataset[name].values
        return (values >= low) & (values <= high)

    if selection.time and "time" in roles:
        low = np.datetime64(pd.Timestamp(selection.time.start, tz="UTC").tz_localize(None))
        high = np.datetime64(pd.Timestamp(selection.time.end, tz="UTC").tz_localize(None))
        stamps = pd.DatetimeIndex(dataset[roles["time"]].values).tz_localize(None)
        keep &= (stamps >= low) & (stamps <= high)
    if selection.depth and "vertical" in roles:
        keep &= within(roles["vertical"], selection.depth.minimum,
                       selection.depth.maximum)
    if selection.area:
        if "latitude" in roles:
            keep &= within(roles["latitude"], selection.area.south,
                           selection.area.north)
        if "longitude" in roles:
            keep &= within(roles["longitude"], selection.area.west,
                           selection.area.east)
    return dataset.isel({OBSERVATION_DIM: np.flatnonzero(keep)})
