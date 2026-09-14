#!/usr/bin/env python3
"""Download and verify a small INCOIS ARGO GridDAP development sample."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
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
DATASET_ID = "incois_argo_10d_VAM"
SOURCE_URL = f"{ERDDAP}/griddap/{DATASET_ID}"
INFO_URL = f"{ERDDAP}/info/{DATASET_ID}/index.json"
REQUIRED_DATA_VARIABLES = ("TEMP", "SAL")
REQUIRED_AXES = ("time", "ZAX", "latitude", "longitude")
EXCLUDED_VARIABLES = {"TERR", "SERR"}

TARGET_LATITUDE = (5.0, 20.0)
TARGET_LONGITUDE = (65.0, 85.0)
TARGET_MAX_DEPTH_METERS = 1000.0

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "data" / "raw" / "samples"
OUTPUT_PATH = OUTPUT_DIR / "incois_argo_10d_VAM_indian_ocean_sample.nc"
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
    data_variables = {row[1] for row in rows if row[0] == "variable"}
    dimensions = {row[1] for row in rows if row[0] == "dimension"}

    missing = set(REQUIRED_DATA_VARIABLES) - data_variables
    if missing:
        raise RuntimeError(f"Required data variables not found: {sorted(missing)}")
    missing_axes = set(REQUIRED_AXES) - dimensions
    if missing_axes:
        raise RuntimeError(f"Required coordinate axes not found: {sorted(missing_axes)}")
    if not EXCLUDED_VARIABLES.issubset(data_variables):
        raise RuntimeError("Expected TERR and SERR fields were not found during inspection")

    return {
        "data_variables": sorted(data_variables),
        "dimensions": sorted(dimensions),
    }


def read_axis(axis: str, context: ssl.SSLContext) -> tuple[str, list[str]]:
    url = f"{SOURCE_URL}.csv?{axis}"
    rows = list(csv.reader(io.StringIO(fetch(url, context).decode("utf-8"))))
    if len(rows) < 3 or rows[0] != [axis]:
        raise RuntimeError(f"Unexpected coordinate response for {axis}: {url}")
    return rows[1][0], [row[0] for row in rows[2:] if row]


def nearest(values: list[float], target: float, prefer_inward: str) -> float:
    if prefer_inward == "above":
        tie_preference = lambda value: 0 if value >= target else 1
    else:
        tie_preference = lambda value: 0 if value <= target else 1
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
            expected = set(REQUIRED_DATA_VARIABLES + REQUIRED_AXES)
            if set(variables) != expected:
                raise RuntimeError(
                    f"Unexpected variables in NetCDF. Expected {sorted(expected)}, found {variables}"
                )
            if EXCLUDED_VARIABLES.intersection(variables):
                raise RuntimeError("Excluded TERR or SERR variable is present")
            if dimensions.get("time") != 1:
                raise RuntimeError(f"Expected one time step, found {dimensions.get('time')}")
            for variable in REQUIRED_DATA_VARIABLES:
                expected_shape = tuple(dimensions[axis] for axis in REQUIRED_AXES)
                if dataset.variables[variable].shape != expected_shape:
                    raise RuntimeError(f"Unexpected shape for {variable}")
    except Exception as exc:
        raise RuntimeError(f"NetCDF verification failed for {path}: {exc}") from exc

    return {"dimensions": dimensions, "variables": variables}


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
    for axis in REQUIRED_AXES:
        units[axis], axes[axis] = read_axis(axis, context)

    selected_time = axes["time"][-1]
    depths = [float(value) for value in axes["ZAX"]]
    selected_depths = [depth for depth in depths if depth <= TARGET_MAX_DEPTH_METERS]
    if not selected_depths:
        raise RuntimeError("No depth coordinate found at or above the requested 1000 m limit")

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
        (str(selected_depths[0]), str(selected_depths[-1])),
        (str(latitude_bounds[0]), str(latitude_bounds[1])),
        (str(longitude_bounds[0]), str(longitude_bounds[1])),
    ]
    query = ",".join(constraint(variable, selections) for variable in REQUIRED_DATA_VARIABLES)
    # Encode brackets and parentheses because this INCOIS Tomcat rejects them
    # unescaped in the HTTP request target.
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
        "selected_depths_meters": selected_depths,
        "variables_included": verified["variables"],
        "variables_excluded": sorted(EXCLUDED_VARIABLES),
        "output_path": str(OUTPUT_PATH.relative_to(REPO_ROOT)),
        "dimensions": verified["dimensions"],
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
