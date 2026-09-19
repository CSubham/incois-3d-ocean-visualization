"""Safe resolution of user-chosen files and folders.

The user picks from configured roots; nothing accepts an absolute path. Every
resolution is checked to land inside its root, so a crafted relative path
cannot escape the exposed directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ingestion.config import SUPPORTED_SUFFIXES, browse_roots
from ingestion.domain.errors import SourceError


@dataclass(frozen=True)
class Entry:
    """One item inside a browsable root."""

    name: str
    relative: str
    is_directory: bool
    supported: bool
    size_bytes: int | None = None


def _root(root_id: str) -> Path:
    roots = browse_roots()
    if root_id not in roots:
        raise SourceError(f"unknown location {root_id!r}")
    return roots[root_id].path


def resolve(root_id: str, relative: str) -> Path:
    """Resolve a relative selection inside a root, refusing any escape."""
    root = _root(root_id).resolve()
    candidate = (root / relative.lstrip("/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise SourceError("selected path lies outside the allowed location")
    if not candidate.exists():
        raise SourceError(f"{relative or root_id} does not exist")
    return candidate


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def list_directory(root_id: str, relative: str = "") -> list[Entry]:
    """List one directory, marking which entries can be imported."""
    target = resolve(root_id, relative)
    if not target.is_dir():
        raise SourceError(f"{relative} is not a folder")
    root = _root(root_id).resolve()
    entries: list[Entry] = []
    for item in sorted(target.iterdir(),
                       key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name.startswith("."):
            continue
        entries.append(Entry(
            name=item.name,
            relative=str(item.relative_to(root)),
            is_directory=item.is_dir(),
            supported=item.is_dir() or is_supported(item),
            size_bytes=None if item.is_dir() else item.stat().st_size,
        ))
    return entries


def supported_files(folder: Path) -> list[Path]:
    """Supported files directly inside a folder.

    One level only: a folder selection inspects what it contains and reports
    it, rather than sweeping a tree and ingesting whatever it finds.
    """
    if not folder.is_dir():
        raise SourceError(f"{folder.name} is not a folder")
    return sorted(item for item in folder.iterdir()
                  if item.is_file() and is_supported(item))
