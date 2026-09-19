"""The canonical ingestion package -- what S2 hands to the storage layer.

This is the whole output of the stage. It carries enough for storage to
persist the dataset without inferring anything: the dataset itself, what shape
it is, which variables and coordinates it holds, where it came from, what was
asked for, and what validation concluded.

Deliberately absent: anything about how storage should persist it. Physical
schema, chunking, compression, layout and indexing are the storage layer's
decisions, not this stage's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import xarray as xr

from ingestion.domain.selection import ImportSelection
from ingestion.domain.validation import ValidationResult


class DatasetGeometry(str, Enum):
    """The scientific shape of a dataset.

    Classified, never flattened: a gridded model field and a set of profiles
    are different things downstream, and collapsing them into one table would
    destroy structure the storage and visualisation layers need.
    """

    GRID = "grid"
    PROFILE = "profile"
    TRAJECTORY = "trajectory"
    TRAJECTORY_PROFILE = "trajectory_profile"
    POINT = "point"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")


@dataclass(frozen=True)
class VariableSpec:
    """One imported variable, as it stands after normalization."""

    name: str
    original_name: str
    units: Optional[str] = None
    standard_name: Optional[str] = None
    long_name: Optional[str] = None
    dimensions: tuple[str, ...] = ()
    fill_value: Any = None


@dataclass(frozen=True)
class CoordinateSet:
    """Which coordinate plays which scientific role.

    Names are the dataset's own. A role that could not be identified is None,
    and whether that is acceptable depends on the geometry.
    """

    time: Optional[str] = None
    vertical: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None

    def identified(self) -> dict[str, str]:
        return {role: name for role, name in vars(self).items() if name}


@dataclass(frozen=True)
class SourceInfo:
    """Where the data came from, in enough detail to trace it back."""

    source_id: str
    source_name: str
    dataset_id: str
    dataset_name: str
    kind: str                      # "remote" | "local"
    location: Optional[str] = None  # endpoint or path, as applicable
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalPackage:
    """The S2 output. Complete, validated, and ready for the storage port."""

    import_id: str
    dataset: xr.Dataset
    geometry: DatasetGeometry
    variables: tuple[VariableSpec, ...]
    coordinates: CoordinateSet
    source: SourceInfo
    selection: ImportSelection
    validation: ValidationResult
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError(
                f"CanonicalPackage[{self.import_id}] carries no variables")
        if not self.validation.passed:
            raise ValueError(
                f"CanonicalPackage[{self.import_id}] built from data that "
                f"failed validation: {self.validation.summary()}")

    def describe(self) -> dict[str, Any]:
        """A plain, serialisable view. Excludes the dataset itself."""
        return {
            "import_id": self.import_id,
            "geometry": self.geometry.value,
            "variables": [v.name for v in self.variables],
            "coordinates": self.coordinates.identified(),
            "sizes": {str(k): int(v) for k, v in self.dataset.sizes.items()},
            "source": {
                "source_id": self.source.source_id,
                "source_name": self.source.source_name,
                "dataset_id": self.source.dataset_id,
                "kind": self.source.kind,
                "location": self.source.location,
            },
            "validation": {
                "passed": self.validation.passed,
                "checks_run": list(self.validation.checks_run),
            },
            "created_at": self.created_at.isoformat(),
        }
