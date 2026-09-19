"""In-repo sources used to exercise the workflow without a network.

These stand in for real providers so the full path -- selection, retrieval,
canonicalization, validation, handoff -- can be tested offline. They are test
doubles, never registered by the application itself.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import xarray as xr

from ingestion.domain.errors import SelectionError
from ingestion.domain.selection import ImportSelection
from ingestion.ports import (
    DatasetMetadata, DatasetRef, FetchResult, RangeInfo, SourceCapabilities,
    SourceDescription, SourcePort, VariableInfo,
)

GRID = "fake_grid"
PROFILES = "fake_profiles"
UNREADABLE = "fake_without_units"


def _grid(times: int = 3) -> xr.Dataset:
    return xr.Dataset(
        {"temperature": (("time", "depth", "lat", "lon"),
                         np.full((times, 4, 6, 8), 12.5),
                         {"units": "degC",
                          "standard_name": "sea_water_temperature"}),
         "salinity": (("time", "depth", "lat", "lon"),
                      np.full((times, 4, 6, 8), 35.0),
                      {"units": "psu", "standard_name": "sea_water_salinity"})},
        coords={
            "time": np.array(["2024-09-01", "2024-09-02", "2024-09-03"],
                             dtype="datetime64[ns]")[:times],
            "depth": [0.0, 10.0, 50.0, 100.0],
            "lat": np.linspace(-5, 20, 6),
            "lon": np.linspace(65, 90, 8),
        })


def _profiles(rows: int = 40) -> xr.Dataset:
    return xr.Dataset(
        {"temperature": (("observation",), np.full(rows, 14.0),
                         {"units": "degC"}),
         "salinity": (("observation",), np.full(rows, 34.8),
                      {"units": "psu"})},
        coords={
            "time": ("observation",
                     np.array(["2024-09-01"] * rows, dtype="datetime64[ns]")),
            "lat": ("observation", np.linspace(1, 9, rows)),
            "lon": ("observation", np.linspace(60, 80, rows)),
            "depth": ("observation", np.linspace(0, 500, rows)),
            "profile_id": ("observation", np.arange(rows) // 10),
        })


def _without_units() -> xr.Dataset:
    dataset = _grid(times=1)
    for name in dataset.data_vars:
        dataset[name].attrs.pop("units", None)
    return dataset


class FakeSource(SourcePort):
    """A provider offering one gridded, one profile and one unusable dataset."""

    source_id = "fake_provider"

    def __init__(self) -> None:
        self.fetches: list[ImportSelection] = []

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id=self.source_id, name="Fake Provider", kind="remote",
            description="Stands in for a real provider.",
            capabilities=SourceCapabilities(
                variable_selection=True, time_subsetting=True,
                depth_subsetting=True, spatial_subsetting=True))

    def list_datasets(self, context: Optional[dict[str, Any]] = None
                      ) -> tuple[DatasetRef, ...]:
        return (
            DatasetRef(dataset_id=GRID, name="Gridded model output"),
            DatasetRef(dataset_id=PROFILES, name="Float profiles"),
            DatasetRef(dataset_id=UNREADABLE, name="Field without units"),
        )

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        dataset = self._dataset(dataset_id)
        return DatasetMetadata(
            dataset_id=dataset_id,
            name=next(ref.name for ref in self.list_datasets()
                      if ref.dataset_id == dataset_id),
            variables=tuple(
                VariableInfo(name=str(name), units=variable.attrs.get("units"),
                             dimensions=tuple(str(d) for d in variable.dims))
                for name, variable in dataset.data_vars.items()),
            ranges=(
                RangeInfo(dimension="depth", role="vertical", minimum=0.0,
                          maximum=100.0, units="m", count=4),
                RangeInfo(dimension="lat", role="latitude", minimum=-5.0,
                          maximum=20.0, units="degrees_north", count=6),
            ))

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        self.fetches.append(selection)
        dataset = self._dataset(selection.dataset_id)
        if selection.variables:
            unknown = set(selection.variables) - set(map(str, dataset.data_vars))
            if unknown:
                raise SelectionError("no variable(s) named "
                                     + ", ".join(sorted(unknown)))
            dataset = dataset[list(selection.variables)]
        if selection.depth and "depth" in dataset.dims:
            dataset = dataset.sel(depth=slice(selection.depth.minimum,
                                              selection.depth.maximum))
        return FetchResult(dataset=dataset,
                           location=f"fake://{selection.dataset_id}")

    @staticmethod
    def _dataset(dataset_id: str) -> xr.Dataset:
        if dataset_id == GRID:
            return _grid()
        if dataset_id == PROFILES:
            return _profiles()
        if dataset_id == UNREADABLE:
            return _without_units()
        raise SelectionError(f"no dataset named {dataset_id!r}")
