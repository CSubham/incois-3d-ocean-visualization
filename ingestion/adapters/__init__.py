"""Source resolution.

The application service asks for a source by id and receives a `SourcePort`.
It never learns what is behind that source -- routing happens here, at the
adapter boundary.

Adding a source means adding an entry to this table and its adapter module.
Local file sources are currently archived; see `archive/local-sources/`.
"""

from __future__ import annotations

from typing import Callable

from ingestion.config import ERDDAP_SERVERS
from ingestion.domain.errors import SourceError
from ingestion.adapters.erddap import ErddapAdapter
from ingestion.ports import SourceDescription, SourcePort

#: Source id -> how to build the adapter for it.
_BUILDERS: dict[str, Callable[[], SourcePort]] = {}

for _server in ERDDAP_SERVERS:
    _BUILDERS[_server.source_id] = (
        lambda server=_server: ErddapAdapter(server))


def resolve(source_id: str) -> SourcePort:
    """The adapter for one source."""
    builder = _BUILDERS.get(source_id)
    if builder is None:
        raise SourceError(f"unknown source {source_id!r}")
    return builder()


def available_sources() -> tuple[SourceDescription, ...]:
    """Every source a user may choose from, remote first."""
    described = [build().describe() for build in _BUILDERS.values()]
    described.sort(key=lambda d: (d.kind != "remote", d.name))
    return tuple(described)


__all__ = ["resolve", "available_sources", "SourcePort"]
