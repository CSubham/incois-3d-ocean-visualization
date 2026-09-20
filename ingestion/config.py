"""Deployment configuration for the ingestion stage.

Every endpoint, root and limit is declared here rather than inline in
application logic, so a deployment is configured by environment rather than by
editing modules. Source-specific settings sit with the source that needs them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


# -- Where retrieved data is written ---------------------------------------

DOWNLOAD_ROOT: Path = _path("INGESTION_DOWNLOAD_ROOT",
                            REPO_ROOT / "data" / "acquired")


# -- Remote sources ---------------------------------------------------------

@dataclass(frozen=True)
class ErddapServer:
    """An ERDDAP deployment and the datasets exposed from it."""

    source_id: str
    name: str
    base_url: str
    description: str = ""
    #: Restricts what is offered to these dataset ids. Empty -- the default --
    #: means offer whatever the server publishes that this adapter can read.
    datasets: tuple[str, ...] = ()
    #: Guards against a selection that would pull an unreasonable volume.
    max_values_per_request: int = 2_000_000
    timeout_seconds: int = 120
    #: Some servers omit intermediate certificates; supplying one completes
    #: the chain without weakening verification.
    extra_ca_bundle: Path | None = None


INCOIS_ERDDAP = ErddapServer(
    source_id="incois_erddap",
    name="INCOIS ERDDAP",
    base_url=os.environ.get("INCOIS_ERDDAP_URL",
                            "https://erddap.incois.gov.in/erddap"),
    description="Indian National Centre for Ocean Information Services.",
    max_values_per_request=int(
        os.environ.get("INCOIS_MAX_REQUEST_VALUES", "2000000")),
    extra_ca_bundle=Path(__file__).parent / "certs"
                    / "globalsign_rsa_ov_ssl_ca_2018.pem",
)

#: Global products, for coverage the regional INCOIS holdings cannot give:
#: longitudes expressed -180 to 180, the antimeridian, and high latitudes.
#:
#: NOAA CoastWatch was the first candidate and is unreachable from here --
#: "no route to host" at the network level, not a fault in this code.
IFREMER = ErddapServer(
    source_id="ifremer_erddap",
    name="Ifremer",
    base_url=os.environ.get("IFREMER_ERDDAP_URL",
                            "https://erddap.ifremer.fr/erddap"),
    description="French national ocean data centre. Global products.",
)

ERDDAP_SERVERS: tuple[ErddapServer, ...] = (INCOIS_ERDDAP, IFREMER)
