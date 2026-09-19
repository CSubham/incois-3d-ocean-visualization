"""Shared behaviour for adapters over files the user has chosen.

A local dataset is identified as ``root_id:relative/path``. The root is one of
the configured browsable locations, so an identifier can never address a file
outside them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ingestion import local_paths
from ingestion.config import browse_roots
from ingestion.domain.errors import SourceError
from ingestion.ports import DatasetRef, SourcePort


class LocalSourceAdapter(SourcePort):
    """Base for adapters that read files from configured locations."""

    #: File suffixes this adapter is able to read.
    suffixes: tuple[str, ...] = ()

    @staticmethod
    def encode(root_id: str, relative: str) -> str:
        return f"{root_id}:{relative}"

    @staticmethod
    def decode(dataset_id: str) -> tuple[str, str]:
        root_id, separator, relative = dataset_id.partition(":")
        if not separator:
            raise SourceError(f"{dataset_id!r} is not a valid file selection")
        return root_id, relative

    def resolve(self, dataset_id: str) -> Path:
        root_id, relative = self.decode(dataset_id)
        path = local_paths.resolve(root_id, relative)
        if not path.is_file():
            raise SourceError(f"{path.name} is not a file")
        if self.suffixes and path.suffix.lower() not in self.suffixes:
            raise SourceError(
                f"{path.name} is not a file this source can read")
        return path

    def handles(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def list_datasets(self, context: Optional[dict[str, Any]] = None
                      ) -> tuple[DatasetRef, ...]:
        """Files this adapter can read at the location the user is browsing."""
        context = context or {}
        root_id = context.get("root_id") or next(iter(browse_roots()), "")
        relative = context.get("path", "")
        folder = local_paths.resolve(root_id, relative)
        if folder.is_file():
            candidates = [folder] if self.handles(folder) else []
            root = browse_roots()[root_id].path.resolve()
        else:
            candidates = [p for p in local_paths.supported_files(folder)
                          if self.handles(p)]
            root = browse_roots()[root_id].path.resolve()
        return tuple(
            DatasetRef(
                dataset_id=self.encode(root_id, str(path.relative_to(root))),
                name=path.name,
                description=f"{path.stat().st_size:,} bytes",
                details={"path": str(path)},
            )
            for path in candidates
        )
