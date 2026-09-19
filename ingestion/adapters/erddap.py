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

    def _url(self, dataset_id: str, suffix: str = "") -> str:
        return f"{self.server.base_url}/griddap/{dataset_id}{suffix}"

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
                       details={"institution": entry["institution"]})
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
            # Only gridded datasets: this adapter retrieves through griddap,
            # so anything else would be listed and then fail on selection.
            if grid is not None and not row[grid]:
                continue
            dataset_id = str(row[identifier])
            heading = str(row[title]) if title is not None else dataset_id
            found.append({
                "dataset_id": dataset_id,
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
            role = _ROLE_BY_NAME.get(axis.lower(), axis.lower())
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
