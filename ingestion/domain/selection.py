"""What the user asked to import.

One object carries every runtime choice. Nothing downstream of the application
service reads configuration to decide how much data to bring in -- it arrives
here or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ingestion.domain.errors import SelectionError


@dataclass(frozen=True)
class TimeRange:
    start: str
    end: str


@dataclass(frozen=True)
class DepthRange:
    minimum: float
    maximum: float


@dataclass(frozen=True)
class Area:
    """Geographic bounds, in degrees."""

    west: float
    east: float
    south: float
    north: float


@dataclass(frozen=True)
class ImportSelection:
    """A complete, self-describing import request.

    `source_id` names the source; `dataset_id` names what to take from it.
    Neither is interpreted by the application service -- both are handed to the
    adapter the source resolves to.
    """

    source_id: str
    dataset_id: str
    variables: tuple[str, ...] = ()
    time: Optional[TimeRange] = None
    depth: Optional[DepthRange] = None
    area: Optional[Area] = None

    def __post_init__(self) -> None:
        if not self.source_id:
            raise SelectionError("no source chosen")
        if not self.dataset_id:
            raise SelectionError("no dataset chosen")

    def requested_ranges(self) -> dict[str, bool]:
        return {
            "variable_selection": bool(self.variables),
            "time_subsetting": self.time is not None,
            "depth_subsetting": self.depth is not None,
            "spatial_subsetting": self.area is not None,
        }
