"""ERDDAP source adapter.

Speaks the ERDDAP GridDAP protocol. Everything provider-specific -- endpoint,
TLS peculiarities, constraint syntax, axis discovery -- stays inside this
module; the application service knows only `SourcePort`.

The adapter is configured with an `ErddapServer`, so a second ERDDAP
deployment is a configuration entry rather than a new module.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import ssl
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import xarray as xr

from ingestion.config import DOWNLOAD_ROOT, ErddapServer
from ingestion.domain.errors import SelectionError, SourceError
from ingestion.domain.selection import ImportSelection
from ingestion.tools import delimited
from ingestion.tools.delimited import is_ancillary, role_of
from ingestion.ports import (
    DatasetMetadata, DatasetRef, FetchResult, RangeInfo, SourceCapabilities,
    SourceDescription, SourcePort, VariableInfo,
)

USER_AGENT = "incois-ingestion/1.0"

#: Remote providers drop connections. A bounded retry covers the transient
#: case without hiding a provider that is genuinely down.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0

#: ERDDAP names axes freely; these map the common spellings onto the
#: scientific role each plays.
_ROLE_BY_NAME: dict[str, str] = {
    "time": "time",
    "zax": "vertical", "depth": "vertical", "z": "vertical",
    "altitude": "vertical", "pressure": "vertical",
    "latitude": "latitude", "lat": "latitude",
    "longitude": "longitude", "lon": "longitude",
}


class ErddapAdapter(SourcePort):
    """One ERDDAP deployment, exposed as a source."""

    def __init__(self, server: ErddapServer) -> None:
        self.server = server
        self._catalogue_cache: Optional[list[dict[str, str]]] = None

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

    # -- transport ----------------------------------------------------------

    def _context(self) -> ssl.SSLContext:
        if os.environ.get("INGESTION_ALLOW_INSECURE_TLS") == "1":
            return ssl._create_unverified_context()  # noqa: SLF001
        context = ssl.create_default_context()
        bundle = self.server.extra_ca_bundle
        if bundle and Path(bundle).exists():
            context.load_verify_locations(cafile=str(bundle))
        return context

    def _get(self, url: str, timeout: int = 60) -> bytes:
        request = Request(url, headers={"User-Agent": USER_AGENT})

        def attempt() -> bytes:
            with urlopen(request, context=self._context(),
                         timeout=timeout) as response:
                return response.read()

        return self._with_retry(attempt)

    def _with_retry(self, action):
        """Run a request, retrying only what is worth retrying.

        A refusal is reported immediately; a dropped or timed-out connection
        is tried again, because that is usually the network rather than the
        provider.
        """
        last: Exception | None = None
        for attempt_number in range(RETRY_ATTEMPTS):
            try:
                return action()
            except HTTPError as exc:
                if exc.code == 503:
                    raise SourceError(
                        f"{self.server.name} is unavailable right now "
                        "(the provider reports maintenance downtime)") from exc
                raise SourceError(
                    f"{self.server.name} refused the request: {exc}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt_number < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt_number + 1))
        raise SourceError(
            f"{self.server.name} could not be reached after "
            f"{RETRY_ATTEMPTS} attempts: {last}") from last

    def _table_columns(self, dataset_id: str) -> list[str]:
        """Every column a tabledap dataset publishes."""
        return [str(row[1]) for row in self._info_rows(dataset_id)
                if row[0] == "variable"]

    def _column_units(self, dataset_id: str) -> dict[str, str]:
        """What each column measures in, as the catalogue records it."""
        units: dict[str, str] = {}
        for row in self._info_rows(dataset_id):
            if row[0] == "attribute" and row[1] != "NC_GLOBAL" \
                    and str(row[2]) == "units":
                units[str(row[1])] = str(row[4])
        return units

    def _protocol_of(self, dataset_id: str) -> str:
        """How this dataset is served. Decided by the catalogue, not guessed."""
        for entry in self._catalogue():
            if entry["dataset_id"] == dataset_id:
                return entry["protocol"]
        raise SourceError(f"{dataset_id!r} is not offered by "
                          f"{self.server.name}")

    def _url(self, dataset_id: str, suffix: str = "",
             protocol: str = "griddap") -> str:
        return f"{self.server.base_url}/{protocol}/{dataset_id}{suffix}"

    # -- discovery ----------------------------------------------------------

    def list_datasets(self, context: Optional[dict[str, Any]] = None
                      ) -> tuple[DatasetRef, ...]:
        """Whatever the server publishes that this adapter can read.

        The catalogue carries titles and summaries, so one request describes
        every dataset -- there is no need to ask about them one by one.
        """
        allowed = set(self.server.datasets)
        refs = [
            DatasetRef(dataset_id=entry["dataset_id"], name=entry["title"],
                       # Where a dataset says nothing useful about itself,
                       # naming who publishes it beats naming nothing.
                       description=entry["summary"] or entry["institution"],
                       details={"institution": entry["institution"],
                                "protocol": entry["protocol"]})
            for entry in self._catalogue()
            if not allowed or entry["dataset_id"] in allowed
        ]
        refs.sort(key=lambda ref: ref.name.lower())
        return tuple(refs)

    def _catalogue(self) -> list[dict[str, str]]:
        """Every griddap dataset on the server, from its published index."""
        if self._catalogue_cache is not None:
            return self._catalogue_cache

        raw = self._get(f"{self.server.base_url}/info/index.json"
                        "?page=1&itemsPerPage=10000")
        try:
            table = json.loads(raw)["table"]
            columns = table["columnNames"]
            rows = table["rows"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SourceError(
                f"{self.server.name} returned a catalogue that could not be "
                "read") from exc

        def index_of(*names: str) -> Optional[int]:
            for name in names:
                if name in columns:
                    return columns.index(name)
            return None

        grid = index_of("griddap")
        table = index_of("tabledap")
        identifier = index_of("Dataset ID", "datasetID")
        title = index_of("Title", "title")
        summary = index_of("Summary", "summary")
        institution = index_of("Institution", "institution")
        if identifier is None:
            raise SourceError(
                f"{self.server.name} published a catalogue without dataset "
                "identifiers")

        found: list[dict[str, str]] = []
        for row in rows:
            # A server may publish the same holding both ways. griddap is
            # preferred where offered: it returns arrays directly, where
            # tabledap returns rows that must be rebuilt into one.
            protocol = ""
            if grid is not None and row[grid]:
                protocol = "griddap"
            elif table is not None and row[table]:
                protocol = "tabledap"
            if not protocol:
                continue
            dataset_id = str(row[identifier])
            if dataset_id == "allDatasets":
                continue        # ERDDAP's own index of itself
            heading = str(row[title]) if title is not None else dataset_id
            found.append({
                "dataset_id": dataset_id,
                "protocol": protocol,
                "title": heading,
                "summary": _readable_summary(
                    str(row[summary]) if summary is not None else "", heading),
                "institution": (str(row[institution])
                                if institution is not None else ""),
            })
        self._catalogue_cache = found
        return found

    def _info_rows(self, dataset_id: str) -> list[list[Any]]:
        raw = self._get(
            f"{self.server.base_url}/info/{dataset_id}/index.json")
        try:
            return json.loads(raw)["table"]["rows"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SourceError(
                f"{self.server.name} returned metadata that could not be "
                "read") from exc

    def _attributes(self, dataset_id: str) -> dict[str, str]:
        return {str(row[2]): str(row[4]) for row in self._info_rows(dataset_id)
                if row[0] == "attribute" and row[1] == "NC_GLOBAL"}

    # -- dimension extents, read from metadata rather than fetched ---------

    @staticmethod
    def _dimension_rows(rows: list[list[Any]]) -> dict[str, dict[str, Any]]:
        """Extent, spacing and size for each axis, from the info response.

        ERDDAP reports all of this in its metadata, so a full axis download is
        never needed to describe or bound a selection. Value-based constraints
        are snapped to real coordinates by the server itself.
        """
        described: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row[0] == "dimension":
                detail = str(row[4])
                count = re.search(r"nValues=(\d+)", detail)
                spacing = re.search(r"averageSpacing=([-\d.eE+]+)", detail)
                described.setdefault(str(row[1]), {}).update({
                    "count": int(count.group(1)) if count else None,
                    "spacing": float(spacing.group(1)) if spacing else None,
                })
            elif row[0] == "attribute" and str(row[2]) in (
                    "actual_range", "units"):
                described.setdefault(str(row[1]), {})[str(row[2])] = str(row[4])
        return described

    @staticmethod
    def _epoch_to_iso(value: float, units: Optional[str]) -> str:
        """Render a CF time value as an ISO instant."""
        if not units:
            return str(value)
        match = re.match(r"\s*(\w+)\s+since\s+(.+)", units, re.IGNORECASE)
        if not match:
            return str(value)
        scale = {"seconds": 1.0, "second": 1.0, "minutes": 60.0,
                 "minute": 60.0, "hours": 3600.0, "hour": 3600.0,
                 "days": 86400.0, "day": 86400.0}.get(match.group(1).lower())
        if scale is None:
            return str(value)
        try:
            origin = datetime.fromisoformat(
                match.group(2).strip().replace("Z", "+00:00"))
        except ValueError:
            return str(value)
        if origin.tzinfo is None:
            origin = origin.replace(tzinfo=timezone.utc)
        moment = origin.timestamp() + value * scale
        return datetime.fromtimestamp(moment, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

    def _ranges(self, rows: list[list[Any]], axes: list[str]
                ) -> tuple[RangeInfo, ...]:
        described = self._dimension_rows(rows)
        ranges: list[RangeInfo] = []
        for axis in axes:
            detail = described.get(axis, {})
            role = role_of(axis) or _ROLE_BY_NAME.get(axis.lower(),
                                                       axis.lower())
            units = detail.get("units")
            extent = detail.get("actual_range")
            low = high = None
            if extent:
                try:
                    low, high = (float(part) for part in extent.split(",")[:2])
                except ValueError:
                    low = high = None
            if low is not None and role == "time":
                minimum: Any = self._epoch_to_iso(low, units)
                maximum: Any = self._epoch_to_iso(high, units)
                units = "UTC"
            else:
                minimum, maximum = low, high
            ranges.append(RangeInfo(
                dimension=axis, role=role, minimum=minimum, maximum=maximum,
                units=units, count=detail.get("count")))
        return tuple(ranges)

    # -- inspection ---------------------------------------------------------

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        allowed = set(self.server.datasets)
        if allowed and dataset_id not in allowed:
            raise SourceError(f"{dataset_id!r} is not offered by "
                              f"{self.server.name}")
        protocol = self._protocol_of(dataset_id)
        rows = self._info_rows(dataset_id)
        axes = [str(row[1]) for row in rows if row[0] == "dimension"]

        described: dict[str, dict[str, str]] = {}
        globals_: dict[str, str] = {}
        for row in rows:
            if row[0] != "attribute":
                continue
            if row[1] == "NC_GLOBAL":
                globals_[str(row[2])] = str(row[4])
            else:
                described.setdefault(str(row[1]), {})[str(row[2])] = str(row[4])

        variables = tuple(
            VariableInfo(
                name=str(row[1]),
                units=described.get(str(row[1]), {}).get("units"),
                long_name=described.get(str(row[1]), {}).get("long_name"),
                standard_name=described.get(str(row[1]), {}).get(
                    "standard_name"),
                dimensions=tuple(axes))
            for row in rows
            if row[0] == "variable" and str(row[1]) not in axes)

        if protocol == "tabledap":
            # No dimensions to read: a table's extent lives on the columns
            # that carry a scientific role. One column per role, and never a
            # flag or an adjusted copy -- a table names its position and
            # depth once, then qualifies them repeatedly.
            axes = []
            claimed: set[str] = set()
            for row in rows:
                if row[0] != "variable":
                    continue
                name = str(row[1])
                if is_ancillary(name):
                    continue
                role = role_of(name)
                if role and role not in claimed:
                    claimed.add(role)
                    axes.append(name)
            variables = tuple(v for v in variables
                              if not role_of(v.name) and not is_ancillary(v.name))

        return DatasetMetadata(
            dataset_id=dataset_id,
            name=globals_.get("title", dataset_id),
            variables=variables,
            ranges=self._ranges(rows, axes),
            attributes=globals_,
        )

    # -- retrieval ----------------------------------------------------------

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        """Retrieve, by whichever protocol the catalogue says this is.

        The choice is internal. Nothing above this adapter learns that a
        server serves some holdings as arrays and others as rows.
        """
        if self._protocol_of(selection.dataset_id) == "tabledap":
            return self._fetch_rows(selection)
        return self._fetch_grid(selection)

    # -- rows, from tabledap ------------------------------------------------

    def _fetch_rows(self, selection: ImportSelection) -> FetchResult:
        dataset_id = selection.dataset_id
        metadata = self.inspect_dataset(dataset_id)
        available = {v.name for v in metadata.variables}
        chosen = list(dict.fromkeys(selection.variables)) or sorted(available)
        unknown = set(chosen) - available
        if unknown:
            raise SelectionError("this dataset has no variable(s) named "
                                 + ", ".join(sorted(unknown)))

        axes = {info.role: info.dimension for info in metadata.ranges}
        # Position, time and depth come back whatever was asked for: without
        # them a measurement cannot be placed, and validation would reject it.
        columns = [axes[role] for role in
                   ("time", "latitude", "longitude", "vertical")
                   if role in axes]

        published = self._table_columns(dataset_id)

        # Platform and cycle identifiers come back too. Without them a set of
        # rows cannot be grouped into casts, and the same float measured over
        # days reads as a single path through the water rather than as the
        # profiles it is. Selecting one float later (IDO-002) needs them.
        columns += [name for name in published
                    if is_ancillary(name) and not _is_flag(name)
                    and name not in columns]

        columns += [name for name in chosen if name not in columns]

        # Quality flags for what was chosen: which measurements to trust is
        # not a detail to discard on the way in.
        columns += [f"{name}_QC" for name in chosen
                    if f"{name}_QC" in published and f"{name}_QC" not in columns]

        constraints: list[str] = []

        def bound(role: str, low: Any, high: Any) -> None:
            column = axes.get(role)
            if column is None:
                return
            constraints.append(f"&{column}>={low}")
            constraints.append(f"&{column}<={high}")

        if selection.time:
            bound("time", selection.time.start, selection.time.end)
        if selection.depth:
            bound("vertical", selection.depth.minimum, selection.depth.maximum)
        if selection.area:
            bound("latitude", selection.area.south, selection.area.north)
            bound("longitude", selection.area.west, selection.area.east)

        # A table has no shape to measure before asking, so the guard becomes
        # a row limit rather than a refusal.
        limit = max(1, self.server.max_values_per_request // max(len(columns), 1))
        query = (",".join(columns) + "".join(constraints)
                 + f'&orderByLimit("{limit}")')
        url = f"{self._url(dataset_id, '.csv', 'tabledap')}?" + quote(
            query, safe=",&:")

        try:
            text = self._get(url, timeout=self.server.timeout_seconds).decode()
        except SourceError as exc:
            # ERDDAP answers an empty selection with a refusal, not an empty
            # table, so say what actually happened.
            if "refused" in str(exc):
                raise SelectionError(
                    "no observations match that selection") from exc
            raise

        # The catalogue already said what each column measures in, so the
        # file is not asked to describe itself.
        declared = {name: units for name, units in
                    self._column_units(dataset_id).items() if units}
        dataset = delimited.read(text, units=declared)
        rows = int(dataset.sizes.get(delimited.OBSERVATION_DIM, 0))
        if rows == 0:
            raise SelectionError("no observations match that selection")

        return FetchResult(
            dataset=dataset,
            location=url,
            details={"provider": self.server.name, "dataset_id": dataset_id,
                     "request_url": url, "rows": rows, "row_limit": limit,
                     "truncated": rows >= limit,
                     "protocol": "tabledap"},
        )

    # -- arrays, from griddap -----------------------------------------------

    def _fetch_grid(self, selection: ImportSelection) -> FetchResult:
        dataset_id = selection.dataset_id
        metadata = self.inspect_dataset(dataset_id)
        available = {v.name for v in metadata.variables}
        chosen = list(dict.fromkeys(selection.variables)) or sorted(available)
        unknown = set(chosen) - available
        if unknown:
            raise SelectionError("this dataset has no variable(s) named "
                                 + ", ".join(sorted(unknown)))

        constraints: list[tuple[str, str]] = []
        estimate = len(chosen)
        for info in metadata.ranges:
            low, high = _clamp(info, selection)
            constraints.append((low, high))
            estimate *= _points(info, low, high)

        if estimate > self.server.max_values_per_request:
            raise SelectionError(
                f"that selection is about {estimate:,} values. Narrow the "
                f"range or choose fewer variables to stay under "
                f"{self.server.max_values_per_request:,}.")

        query = ",".join(
            name + "".join(f"[({low}):1:({high})]" for low, high in constraints)
            for name in chosen)
        url = f"{self._url(dataset_id, '.nc')}?{quote(query, safe=',:-')}"
        path = self._download(url, dataset_id)

        try:
            dataset = xr.open_dataset(path)
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise SourceError(
                f"the file returned by {self.server.name} could not be "
                f"read: {exc}") from exc

        return FetchResult(
            dataset=dataset,
            location=str(path),
            details={"provider": self.server.name,
                     "dataset_id": dataset_id,
                     "request_url": url,
                     "estimated_values": estimate,
                     "file_size_bytes": path.stat().st_size,
                     "axes": {i.role: i.dimension for i in metadata.ranges}},
        )

    def _download(self, url: str, dataset_id: str) -> Path:
        """Stream to a temporary file and move into place only on success."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = DOWNLOAD_ROOT / dataset_id / f"{dataset_id}_{stamp}.nc"
        destination.parent.mkdir(parents=True, exist_ok=True)
        def attempt() -> Path:
            partial: Path | None = None
            try:
                request = Request(url, headers={"User-Agent": USER_AGENT})
                with urlopen(request, context=self._context(),
                             timeout=self.server.timeout_seconds) as response:
                    with tempfile.NamedTemporaryFile(
                            dir=destination.parent,
                            prefix=f".{destination.name}.",
                            suffix=".part", delete=False) as handle:
                        partial = Path(handle.name)
                        while chunk := response.read(1024 * 1024):
                            handle.write(chunk)
                os.replace(partial, destination)
                return destination
            except BaseException:
                if partial is not None:
                    partial.unlink(missing_ok=True)
                raise

        return self._with_retry(attempt)


def _is_flag(name: str) -> bool:
    """A quality flag, as opposed to an identifier."""
    lowered = name.lower()
    return any(marker in lowered
               for marker in ("_qc", "_flag", "qartod", "_quality"))


#: ERDDAP appends machine-readable metadata to its summaries. Everything from
#: here on describes the file format rather than the data, so it is dropped.
_SUMMARY_NOISE = ("cdm_data_type", "VARIABLES (", "acknowledgement =",
                  "Conventions =", "infoUrl =", "institution =")


def _readable_summary(text: str, title: str) -> str:
    """The part of a summary a person would actually want to read.

    Often nothing survives, because the summary was the title followed by
    format metadata. An empty description is better than a misleading one.
    """
    for marker in _SUMMARY_NOISE:
        position = text.find(marker)
        if position != -1:
            text = text[:position]
    text = " ".join(text.split()).strip(" .;,")
    # Summaries often open by repeating the title; say it once.
    if text.lower().startswith(title.lower()):
        text = text[len(title):].strip(" .;,-–—")
    if len(text) > 150:
        text = text[:150].rsplit(" ", 1)[0] + "…"
    return text


# -- turning a selection into axis constraints -------------------------------

def _requested(role: str, selection: ImportSelection
               ) -> Optional[tuple[Any, Any]]:
    if role == "time" and selection.time:
        return selection.time.start, selection.time.end
    if role == "vertical" and selection.depth:
        return selection.depth.minimum, selection.depth.maximum
    if role == "latitude" and selection.area:
        return selection.area.south, selection.area.north
    if role == "longitude" and selection.area:
        return selection.area.west, selection.area.east
    return None


def _clamp(info: RangeInfo, selection: ImportSelection) -> tuple[str, str]:
    """Bound a request to the extent the axis actually covers.

    Values, not indices: ERDDAP resolves a value constraint to the nearest
    real coordinate, so the axis never has to be downloaded to do it here.
    """
    requested = _requested(info.role, selection)
    if requested is None or info.minimum is None:
        return str(info.minimum), str(info.maximum)

    low, high = requested
    if info.role == "time":
        # Compared as instants, not as text: "2010-12-29" and
        # "2010-12-29T00:00:00Z" are the same moment but not the same string.
        try:
            requested_low, requested_high = _seconds(low), _seconds(high)
            available_low = _seconds(info.minimum)
            available_high = _seconds(info.maximum)
        except (TypeError, ValueError) as exc:
            raise SelectionError(f"{low!r} is not a valid date") from exc
        if requested_low > requested_high:
            raise SelectionError("the start date must not be after the end date")
        if requested_high < available_low or requested_low > available_high:
            raise SelectionError(
                f"this dataset only covers {info.minimum} to {info.maximum}")
        return (str(info.minimum) if requested_low < available_low else str(low),
                str(info.maximum) if requested_high > available_high else str(high))

    try:
        low, high = float(low), float(high)
    except (TypeError, ValueError) as exc:
        raise SelectionError(f"{info.dimension} bounds must be numbers") from exc
    if low > high:
        # A west greater than its east, both inside the axis, is not a mistake
        # -- it is an area crossing the antimeridian. Saying "minimum exceeds
        # maximum" blames the user for asking something reasonable.
        if (info.role == "longitude"
                and float(info.minimum) <= high
                and low <= float(info.maximum)):
            raise SelectionError(
                "an area crossing the antimeridian is not supported. Request "
                f"it as two areas: {low} to {info.maximum}, and "
                f"{info.minimum} to {high}.")
        raise SelectionError(
            f"{info.dimension} minimum must not exceed its maximum")
    if high < float(info.minimum) or low > float(info.maximum):
        raise SelectionError(
            f"{info.dimension} must fall within {info.minimum} to "
            f"{info.maximum}")
    return (str(max(low, float(info.minimum))),
            str(min(high, float(info.maximum))))


def _points(info: RangeInfo, low: str, high: str) -> int:
    """How many coordinates a bounded axis covers, for a size estimate.

    Every axis is costed by the share of its extent the selection covers,
    dates included -- costing time at its full length would reject a request
    for a fortnight out of twenty years.
    """
    if not info.count or info.minimum is None:
        return info.count or 1

    if info.role == "time":
        try:
            extent = _seconds(info.maximum) - _seconds(info.minimum)
            span = _seconds(high) - _seconds(low)
        except (TypeError, ValueError):
            return info.count
    else:
        try:
            extent = abs(float(info.maximum) - float(info.minimum))
            span = abs(float(high) - float(low))
        except (TypeError, ValueError):
            return info.count

    if extent <= 0:
        return 1
    share = max(0.0, min(1.0, span / extent))
    return max(1, round(info.count * share))


def _seconds(value: Any) -> float:
    """An ISO instant as a number, for comparing spans."""
    text = str(value).replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()
