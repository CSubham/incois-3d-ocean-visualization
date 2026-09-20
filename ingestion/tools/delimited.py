"""Reading delimited observation text into a dataset.

ERDDAP's tabledap serves CSV as a header row, a units row, and then values.
Units therefore arrive with the data and are never inferred from a column
name -- a column whose units are absent stays unitless and is caught by
validation rather than guessed at.

Rows are kept as rows. Observations are not a grid, and flattening them onto
one would invent structure the source does not have.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Optional

import numpy as np
import pandas as pd
import xarray as xr

from ingestion.domain.errors import SourceError

OBSERVATION_DIM = "observation"

#: Column names that carry a scientific role rather than a measurement.
_ROLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "time": ("time", "date", "datetime", "juld"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon"),
    "vertical": ("pres", "pressure", "depth", "dbar", "z"),
}

#: Quality flags and platform identifiers describe a measurement without
#: being one, so they are kept as coordinates rather than offered as
#: variables. They legitimately carry no units.
_FLAG_MARKERS = ("_qc", "_flag", "qartod", "_quality")
_IDENTIFIER_MARKERS = ("platform", "cycle", "station", "profile", "float",
                       "wmo", "trajectory", "cast", "_id", "direction",
                       "date_creation", "date_update")


def role_of(column: str) -> Optional[str]:
    lowered = column.lower()
    for role, names in _ROLE_COLUMNS.items():
        if lowered in names or any(lowered.startswith(n) for n in names):
            return role
    return None


def is_ancillary(column: str) -> bool:
    lowered = column.lower()
    return (any(marker in lowered for marker in _FLAG_MARKERS)
            or any(marker in lowered for marker in _IDENTIFIER_MARKERS))


def _looks_numeric(cell: str) -> bool:
    try:
        float(cell)
        return True
    except (TypeError, ValueError):
        return False


def split_units_row(rows: list[list[str]]) -> tuple[dict[str, str], int]:
    """Separate a units row from the data, if the file carries one.

    Compared against the row below rather than judged alone. "All cells
    non-numeric" seems like the obvious test and is wrong: `1` is a valid
    CF unit for a dimensionless quantity such as practical salinity, and a
    units row containing it would be read as data.
    """
    if len(rows) < 3:
        return {}, 1
    header, second, third = rows[0], rows[1], rows[2]
    if len(second) != len(header) or len(third) != len(header):
        return {}, 1

    numeric_second = sum(_looks_numeric(cell) for cell in second)
    numeric_third = sum(_looks_numeric(cell) for cell in third)
    # A units row is less numeric than the data beneath it.
    if numeric_third <= numeric_second:
        return {}, 1
    return ({name: cell for name, cell in zip(header, second) if cell.strip()},
            2)


def read(text: str, delimiter: str = ",",
         units: Optional[dict[str, str]] = None) -> xr.Dataset:
    """Parse delimited observation text into a row-oriented dataset.

    `units` are what the source declared about itself elsewhere -- a catalogue
    entry, a sidecar. Given them, the file is not asked to describe itself,
    which is more reliable than reading a row and hoping it is a units row.
    """
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise SourceError("the source returned no data")

    sniffed, first_data_row = split_units_row(rows)
    units = {**sniffed, **(units or {})}
    header = rows[0]
    body = rows[first_data_row:]
    if not body:
        raise SourceError("the source returned no rows for that selection")

    frame = pd.DataFrame(body, columns=header)
    return to_dataset(frame, units)


def to_dataset(frame: pd.DataFrame, units: dict[str, str]) -> xr.Dataset:
    """Build an observation-dimensioned dataset, preserving row structure."""
    coords: dict[str, Any] = {}
    data: dict[str, Any] = {}

    for column in frame.columns:
        name = str(column)
        series = frame[column]
        attrs = {"units": units[name]} if name in units else {}
        role = role_of(name)

        if role == "time":
            values = pd.to_datetime(series, errors="coerce",
                                    format="mixed", utc=True)
            values = values.dt.tz_localize(None).to_numpy()
            attrs.pop("units", None)
        else:
            values = pd.to_numeric(series, errors="coerce").to_numpy()
            if np.all(np.isnan(values)):       # genuinely textual
                values = series.to_numpy()

        if role or is_ancillary(name):
            coords[name] = ((OBSERVATION_DIM,), values, attrs)
        else:
            data[name] = ((OBSERVATION_DIM,), values, attrs)

    if not data:
        raise SourceError(
            "the source returned only identifiers and flags, with no "
            "measured values")
    return xr.Dataset(data_vars=data, coords=coords)
