#!/usr/bin/env python3
"""Download and verify a small INCOIS surface-current GridDAP sample."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import ssl
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from scipy.io import netcdf_file


ERDDAP = "https://erddap.incois.gov.in/erddap"
DATASET_ID = "incois_valueadded_products_datasets"
SOURCE_URL = f"{ERDDAP}/griddap/{DATASET_ID}"
INFO_URL = f"{ERDDAP}/info/{DATASET_ID}/index.json"
DATA_VARIABLES = ("GEO_U", "GEO_V")
AXES = ("time", "latitude", "longitude")

TARGET_LATITUDE = (5.0, 20.0)
TARGET_LONGITUDE = (65.0, 85.0)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "samples"
OUTPUT_PATH = OUTPUT_DIR / "incois_valueadded_products_currents_indian_ocean_sample.nc"
MANIFEST_PATH = OUTPUT_PATH.with_suffix(".json")


def ssl_context(insecure: bool) -> ssl.SSLContext:
    if insecure:
        return ssl._create_unverified_context()  # noqa: SLF001
    return ssl.create_default_context()


def fetch(url: str, context: ssl.SSLContext) -> bytes:
    request = Request(url, headers={"User-Agent": "incois-sample-acquisition/1.0"})
    try:
        with urlopen(request, context=context, timeout=60) as response:
            return response.read()
    except URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def inspect_metadata(context: ssl.SSLContext) -> dict[str, Any]:
    metadata = json.loads(fetch(INFO_URL, context))
    rows = metadata["table"]["rows"]
    variables = {row[1] for row in rows if row[0] == "variable"}
    dimensions = {row[1] for row in rows if row[0] == "dimension"}

    missing_variables = set(DATA_VARIABLES) - variables
    if missing_variables:
        raise RuntimeError(f"Required current variables not found: {sorted(missing_variables)}")
    missing_axes = set(AXES) - dimensions
    if missing_axes:
        raise RuntimeError(f"Required coordinate axes not found: {sorted(missing_axes)}")
    if dimensions != set(AXES):
        raise RuntimeError(f"Unexpected dimensions for surface-current dataset: {sorted(dimensions)}")

    variable_metadata: dict[str, dict[str, str]] = {}
    for variable in DATA_VARIABLES:
        attributes = {
            row[2]: row[4]
            for row in rows
            if row[0] == "attribute" and row[1] == variable
        }
        units = attributes.get("units")
        units_source = "units attribute"
        if not units:
            match = re.search(r"\(([^()]+)\)\s*$", attributes.get("long_name", ""))
            if not match:
                raise RuntimeError(f"No units found in live metadata for {variable}")
            units = match.group(1)
            units_source = "long_name; live metadata has no separate units attribute"
        variable_metadata[variable] = {
            "long_name": attributes.get("long_name", ""),
            "units": units,
            "units_source": units_source,
        }

    return {
        "available_data_variables": sorted(variables),
        "dimensions": sorted(dimensions),
        "current_variable_metadata": variable_metadata,
    }


def read_axis(axis: str, context: ssl.SSLContext) -> tuple[str, list[str]]:
    url = f"{SOURCE_URL}.csv?{axis}"
    rows = list(csv.reader(io.StringIO(fetch(url, context).decode("utf-8"))))
    if len(rows) < 3 or rows[0] != [axis]:
        raise RuntimeError(f"Unexpected coordinate response for {axis}: {url}")
    return rows[1][0], [row[0] for row in rows[2:] if row]


def nearest(values: list[float], target: float, prefer_inward: str) -> float:
    def tie_preference(value: float) -> int:
        inward = value >= target if prefer_inward == "above" else value <= target
        return 0 if inward else 1

    return min(values, key=lambda value: (abs(value - target), tie_preference(value)))


def constraint(variable: str, selections: list[tuple[str, str]]) -> str:
    return variable + "".join(f"[({start}):1:({stop})]" for start, stop in selections)


def download(url: str, destination: Path, context: ssl.SSLContext) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "incois-sample-acquisition/1.0"})
    try:
        with urlopen(request, context=context, timeout=120) as response:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
        os.replace(temporary_path, destination)
    except HTTPError as exc:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Download failed with HTTP {exc.code} for {url}: {detail}") from exc
    except Exception:
        if "temporary_path" in locals():
            temporary_path.unlink(missing_ok=True)
        raise


def verify_netcdf(path: Path) -> dict[str, Any]:
    try:
        with netcdf_file(path, "r", mmap=False) as dataset:
            dimensions = {name: int(length) for name, length in dataset.dimensions.items()}
            variables = sorted(dataset.variables)
            expected_variables = set(DATA_VARIABLES + AXES)
            if set(variables) != expected_variables:
                raise RuntimeError(
                    f"Unexpected variables. Expected {sorted(expected_variables)}, found {variables}"
                )
            if set(dimensions) != set(AXES):
                raise RuntimeError(f"Unexpected dimensions in surface sample: {sorted(dimensions)}")
            if dimensions.get("time") != 1:
                raise RuntimeError(f"Expected one time step, found {dimensions.get('time')}")
            expected_shape = tuple(dimensions[axis] for axis in AXES)
            valid_counts: dict[str, int] = {}
            for variable in DATA_VARIABLES:
                current = dataset.variables[variable]
                if current.shape != expected_shape:
                    raise RuntimeError(f"Unexpected shape for {variable}: {current.shape}")
                values = current[:].copy()
                fill_value = float(getattr(current, "_FillValue", -1.0e34))
                valid_counts[variable] = int((values != fill_value).sum())
                if valid_counts[variable] == 0:
                    raise RuntimeError(f"No valid data values found for {variable}")
    except Exception as exc:
        raise RuntimeError(f"NetCDF verification failed for {path}: {exc}") from exc

    return {
        "dimensions": dimensions,
        "variables": variables,
        "valid_value_counts": valid_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification if the INCOIS server omits its intermediate certificate.",
    )
    args = parser.parse_args()
    context = ssl_context(args.insecure)

    inspected = inspect_metadata(context)
    units: dict[str, str] = {}
    axes: dict[str, list[str]] = {}
    for axis in AXES:
        units[axis], axes[axis] = read_axis(axis, context)

    selected_time = axes["time"][-1]
    latitudes = [float(value) for value in axes["latitude"]]
    longitudes = [float(value) for value in axes["longitude"]]
    latitude_bounds = (
        nearest(latitudes, TARGET_LATITUDE[0], "above"),
        nearest(latitudes, TARGET_LATITUDE[1], "below"),
    )
    longitude_bounds = (
        nearest(longitudes, TARGET_LONGITUDE[0], "above"),
        nearest(longitudes, TARGET_LONGITUDE[1], "below"),
    )

    selections = [
        (selected_time, selected_time),
        (str(latitude_bounds[0]), str(latitude_bounds[1])),
        (str(longitude_bounds[0]), str(longitude_bounds[1])),
    ]
    query = ",".join(constraint(variable, selections) for variable in DATA_VARIABLES)
    request_url = f"{SOURCE_URL}.nc?{quote(query, safe=',:-')}"

    download(request_url, OUTPUT_PATH, context)
    verified = verify_netcdf(OUTPUT_PATH)
    manifest = {
        "source_url": SOURCE_URL,
        "metadata_url": INFO_URL,
        "request_url": request_url,
        "selected_time": selected_time,
        "latitude_bounds_degrees_north": list(latitude_bounds),
        "longitude_bounds_degrees_east": list(longitude_bounds),
        "variables_included": verified["variables"],
        "current_variable_metadata": inspected["current_variable_metadata"],
        "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "dimensions": verified["dimensions"],
        "valid_value_counts": verified["valid_value_counts"],
        "file_size_bytes": OUTPUT_PATH.stat().st_size,
        "metadata_inspection": inspected,
        "coordinate_units": units,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tls_verification_disabled": args.insecure,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
