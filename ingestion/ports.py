"""The boundaries of the ingestion stage.

Two ports. Everything source-specific lives behind `SourcePort`; everything
about durable storage lives behind `StoragePort`. The application service
knows only these two interfaces, which is what keeps the central workflow free
of provider conditionals and file-format branching.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import xarray as xr

from ingestion.domain.package import CanonicalPackage
from ingestion.domain.selection import ImportSelection


@dataclass(frozen=True)
class SourceCapabilities:
    """What a source can narrow server-side before data is retrieved."""

    variable_selection: bool = False
    time_subsetting: bool = False
    depth_subsetting: bool = False
    spatial_subsetting: bool = False


@dataclass(frozen=True)
class SourceDescription:
    """A source a user can choose."""

    source_id: str
    name: str
    kind: str                       # "remote" | "local"
    description: str = ""
    capabilities: SourceCapabilities = SourceCapabilities()
    #: True when the user must supply files or a folder before datasets exist.
    requires_user_files: bool = False


@dataclass(frozen=True)
class DatasetRef:
    """One dataset available from a source."""

    dataset_id: str
    name: str
    description: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VariableInfo:
    """A variable a user may choose to import."""

    name: str
    units: Optional[str] = None
    long_name: Optional[str] = None
    standard_name: Optional[str] = None
    dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class RangeInfo:
    """The extent of one dimension, as the source reports it."""

    dimension: str
    role: str                       # time | vertical | latitude | longitude
    minimum: Any
    maximum: Any
    units: Optional[str] = None
    count: Optional[int] = None


@dataclass(frozen=True)
class DatasetMetadata:
    """Everything needed to build a selection against one dataset."""

    dataset_id: str
    name: str
    variables: tuple[VariableInfo, ...] = ()
    ranges: tuple[RangeInfo, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchResult:
    """Retrieved data, before normalization and validation."""

    dataset: xr.Dataset
    location: str
    details: dict[str, Any] = field(default_factory=dict)


class SourcePort(ABC):
    """The one interface every source is reached through.

    A source may be a remote provider or a class of local file. The
    distinction is the adapter's business; the application service treats them
    identically.
    """

    @abstractmethod
    def describe(self) -> SourceDescription:
        """Identify this source and what it can narrow."""

    @abstractmethod
    def list_datasets(self, context: Optional[dict[str, Any]] = None
                      ) -> tuple[DatasetRef, ...]:
        """Datasets this source offers.

        `context` carries what the user supplied where a source needs it --
        chosen files or a folder for local sources. Remote sources ignore it.
        """

    @abstractmethod
    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        """Variables and dimension ranges for one dataset."""

    @abstractmethod
    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        """Retrieve the selected data, narrowing server-side where possible."""


@dataclass(frozen=True)
class StorageReceipt:
    """What the storage layer returns once it has taken a package."""

    import_id: str
    reference: str
    accepted_at: str
    details: dict[str, Any] = field(default_factory=dict)


class StoragePort(ABC):
    """The S2 to S3 boundary.

    Ingestion ends here. What happens beyond this call -- physical layout,
    schema, chunking, indexing, replication -- belongs to the storage layer
    and is deliberately not modelled in this stage.
    """

    @abstractmethod
    def hand_off(self, package: CanonicalPackage) -> StorageReceipt:
        """Take responsibility for a complete, validated package."""
