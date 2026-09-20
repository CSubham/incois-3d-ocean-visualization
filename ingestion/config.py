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
    # Curated, not the whole catalogue. INCOIS publishes 15 gridded datasets;
    # most are satellite surface products -- SST, scatterometer winds,
    # Oceansat -- which are two-dimensional and outside DIR-001 to DIR-003.
    # These four are depth-resolved temperature and salinity analyses, which
    # is the three-dimensional ocean state this system exists to show.
    datasets=("incois_argo_10d_VAM", "incois_argo_10day_McCreary",
              "incois_argo_mnt_VAM", "incois_argo_mnt_McCreary",
              # The observation holding: Argo float profiles, served as rows.
              "Indian_ARGO_Floats"),
    max_values_per_request=int(
        os.environ.get("INCOIS_MAX_REQUEST_VALUES", "2000000")),
    extra_ca_bundle=Path(__file__).parent / "certs"
                    / "globalsign_rsa_ov_ssl_ca_2018.pem",
)

#: Underwater gliders, for DIR-004 and DIR-005. The DAC publishes 999
#: deployments, nearly all of them off the United States. Curated to the ru29
#: missions, which crossed the Indian Ocean and the Bay of Bengal -- the water
#: this system is about, and the deployment the repository already sampled.
IOOS_GLIDERS = ErddapServer(
    source_id="ioos_gliders",
    name="IOOS Glider DAC",
    base_url=os.environ.get("IOOS_GLIDER_URL",
                            "https://gliders.ioos.us/erddap"),
    description="Underwater glider deployments. Depth-resolved profiles "
                "along a track.",
    datasets=("ru29-20180812T0220", "ru29-20190906T1535",
              "ru29-20221116T1326", "ru29-20240419T1430"),
)

ERDDAP_SERVERS: tuple[ErddapServer, ...] = (INCOIS_ERDDAP, IOOS_GLIDERS)


# -- Model sources over OPeNDAP / THREDDS -----------------------------------

@dataclass(frozen=True)
class OpendapDataset:
    """One dataset reachable at an OPeNDAP endpoint.

    Named explicitly rather than discovered. A THREDDS catalogue lists
    everything a centre publishes; this system wants the few products that
    answer the problem statement.
    """

    dataset_id: str
    name: str
    url: str
    description: str = ""


@dataclass(frozen=True)
class OpendapServer:
    """A provider reached over OPeNDAP."""

    source_id: str
    name: str
    datasets: tuple[OpendapDataset, ...]
    description: str = ""
    #: Guards against a selection that would pull an unreasonable volume.
    #: OPeNDAP subsets lazily, so the guard is what keeps a careless request
    #: from asking for the whole globe at every depth and time.
    max_values_per_request: int = 2_000_000


HYCOM = OpendapServer(
    source_id="hycom_opendap",
    name="HYCOM",
    description="Global ocean model output from the HYCOM consortium.",
    datasets=(
        OpendapDataset(
            dataset_id="GLBy0.08_expt_93.0",
            name="HYCOM GLBy0.08 global analysis",
            url=os.environ.get(
                "HYCOM_URL",
                "https://tds.hycom.org/thredds/dodsC/GLBy0.08/expt_93.0"),
            description="Temperature, salinity and current vectors on 40 "
                        "depth levels, 1/12 degree global.",
        ),
    ),
    max_values_per_request=int(
        os.environ.get("HYCOM_MAX_REQUEST_VALUES", "2000000")),
)

OPENDAP_SERVERS: tuple[OpendapServer, ...] = (HYCOM,)
