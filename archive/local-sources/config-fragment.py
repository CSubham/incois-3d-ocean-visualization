"""Configuration the archived local adapters relied on.

Paste back into ingestion/config.py to restore them.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# -- Roots the operator may browse -----------------------------------------

@dataclass(frozen=True)
class BrowseRoot:
    """A directory the deployment exposes for file selection.

    Selection is always relative to one of these. The application never
    accepts an absolute path from the user, so there is no route to arbitrary
    locations on the host.
    """

    root_id: str
    label: str
    path: Path


def browse_roots() -> dict[str, BrowseRoot]:
    configured = os.environ.get("INGESTION_BROWSE_ROOTS")
    if configured:
        roots: dict[str, BrowseRoot] = {}
        for item in configured.split(os.pathsep):
            if not item.strip():
                continue
            root_id, _, raw = item.partition("=")
            resolved = Path(raw or root_id).expanduser().resolve()
            roots[root_id] = BrowseRoot(root_id, root_id.replace("_", " "),
                                        resolved)
        return roots
    return {
        "data": BrowseRoot("data", "Project data", REPO_ROOT / "data" / "raw"),
        "imported": BrowseRoot("imported", "Previously imported",
                               DOWNLOAD_ROOT),
    }


# -- Supported local file kinds --------------------------------------------

NETCDF_SUFFIXES: tuple[str, ...] = (".nc", ".nc4", ".cdf", ".netcdf")
DELIMITED_SUFFIXES: tuple[str, ...] = (".csv", ".tsv", ".txt", ".dat")
SUPPORTED_SUFFIXES: tuple[str, ...] = NETCDF_SUFFIXES + DELIMITED_SUFFIXES
