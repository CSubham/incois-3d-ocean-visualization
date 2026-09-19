"""Folder source adapter.

Discovery and orchestration over the file adapters. A folder is not a format:
this adapter inspects what a chosen folder contains, reports which files can
be read and which cannot, and delegates each supported file to the adapter
that handles it.

Nothing is swept up automatically -- the folder is listed, and the user
chooses what to import from it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ingestion import local_paths
from ingestion.config import browse_roots
from ingestion.domain.errors import SourceError
from ingestion.domain.selection import ImportSelection
from ingestion.adapters.local_base import LocalSourceAdapter
from ingestion.adapters.local_delimited import LocalDelimitedAdapter
from ingestion.adapters.local_netcdf import LocalNetcdfAdapter
from ingestion.ports import (
    DatasetMetadata, DatasetRef, FetchResult, SourceCapabilities,
    SourceDescription,
)

SOURCE_ID = "local_folder"


class LocalFolderAdapter(LocalSourceAdapter):
    """Reads a chosen folder by delegating to the file adapters."""

    def __init__(self) -> None:
        self._delegates: tuple[LocalSourceAdapter, ...] = (
            LocalNetcdfAdapter(), LocalDelimitedAdapter())

    def describe(self) -> SourceDescription:
        return SourceDescription(
            source_id=SOURCE_ID,
            name="Folder",
            kind="local",
            description="A folder you choose. Its supported files are listed "
                        "for you to pick from.",
            capabilities=SourceCapabilities(
                variable_selection=True, time_subsetting=True,
                depth_subsetting=True, spatial_subsetting=True),
            requires_user_files=True,
        )

    # -- delegation ---------------------------------------------------------

    def _delegate_for(self, dataset_id: str) -> LocalSourceAdapter:
        """Route one file to the adapter that reads its format.

        Format detection lives here, inside the local-source mechanism. It
        never reaches the application service.
        """
        _, relative = self.decode(dataset_id)
        suffix = Path(relative).suffix.lower()
        for delegate in self._delegates:
            if suffix in delegate.suffixes:
                return delegate
        raise SourceError(
            f"{Path(relative).name} is not a file type this application "
            "can read")

    # -- discovery ----------------------------------------------------------

    def list_datasets(self, context: Optional[dict[str, Any]] = None
                      ) -> tuple[DatasetRef, ...]:
        """Every supported file in the chosen folder, one level deep."""
        context = context or {}
        root_id = context.get("root_id") or next(iter(browse_roots()), "")
        relative = context.get("path", "")
        folder = local_paths.resolve(root_id, relative)
        if folder.is_file():
            raise SourceError(f"{folder.name} is a file, not a folder")
        root = browse_roots()[root_id].path.resolve()
        refs: list[DatasetRef] = []
        for path in local_paths.supported_files(folder):
            refs.append(DatasetRef(
                dataset_id=self.encode(root_id, str(path.relative_to(root))),
                name=path.name,
                description=f"{path.stat().st_size:,} bytes",
                details={"path": str(path), "readable": True}))
        return tuple(refs)

    def unsupported_files(self, root_id: str, relative: str) -> list[str]:
        """Files in the folder this application cannot read, reported not hidden."""
        folder = local_paths.resolve(root_id, relative)
        return sorted(item.name for item in folder.iterdir()
                      if item.is_file() and not item.name.startswith(".")
                      and not local_paths.is_supported(item))

    def inspect_dataset(self, dataset_id: str,
                        context: Optional[dict[str, Any]] = None
                        ) -> DatasetMetadata:
        return self._delegate_for(dataset_id).inspect_dataset(
            dataset_id, context)

    def fetch(self, selection: ImportSelection,
              context: Optional[dict[str, Any]] = None) -> FetchResult:
        return self._delegate_for(selection.dataset_id).fetch(
            selection, context)
