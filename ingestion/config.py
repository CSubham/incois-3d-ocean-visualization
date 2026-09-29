"""Deployment configuration for the ingestion stage.

Every endpoint, root and limit is declared here rather than inline in
application logic, so a deployment is configured by environment rather than by
editing modules. Source-specific settings sit with the source that needs them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


# -- Storage (S3) -----------------------------------------------------------

#: Where scientific arrays are written. Local files in development; an
#: object-storage backend replaces the store class and nothing else.
OBJECT_STORE_ROOT: Path = _path("INGESTION_OBJECT_STORE",
                                REPO_ROOT / "data" / "store")

#: The catalogue. PostgreSQL with PostGIS, so observation positions can be
#: searched spatially rather than by opening every stored array.
#: Never defaulted: without it the catalogue is refused rather than reached
#: with credentials baked into code. `.env.example` has the local value.
CATALOGUE_DSN: str | None = os.environ.get("INGESTION_CATALOGUE_DSN") or None


def _seconds(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number of seconds, not {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1 second, not {value}")
    return value


#: How long a catalogue connection may take before the request fails,
#: instead of hanging on an unreachable database.
CATALOGUE_CONNECT_TIMEOUT: int = _seconds("INGESTION_CATALOGUE_CONNECT_TIMEOUT", 5)

#: The S3 read implementation is chosen once by the composition root.
S3_QUERY_BACKEND: str = os.environ.get(
    "S3_QUERY_BACKEND", "catalogue").strip().lower()


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


@dataclass(frozen=True)
class ModelSourceReference:
    """Explicit spatial references used only when source CF metadata omits it."""

    crs: str
    vertical_positive: str
    basis: str


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


# HYCOM GLBy0.08 publishes rectilinear longitude/latitude axes in
# degrees_east/degrees_north on the WGS84 geographic grid, and its depth axis
# declares CF ``positive=down``.  The file has no CF grid_mapping variable, so
# this source-backed declaration prevents S3 or S4 from silently guessing.
MODEL_SOURCE_REFERENCES: dict[str, ModelSourceReference] = {
    HYCOM.source_id: ModelSourceReference(
        crs="EPSG:4326",
        vertical_positive="down",
        basis=(
            "HYCOM GLBy0.08 source metadata declares rectilinear longitude "
            "and latitude in degrees_east/degrees_north on WGS84, with the "
            "depth coordinate positive down"
        ),
    ),
}


# Observation sources publish no CF grid mapping for their positions, so each
# is declared here with its basis rather than guessed downstream. Pressure
# and depth both increase downward; pressure is never converted to depth.
OBSERVATION_SOURCE_REFERENCES: dict[str, ModelSourceReference] = {
    INCOIS_ERDDAP.source_id: ModelSourceReference(
        crs="EPSG:4326",
        vertical_positive="down",
        basis=(
            "INCOIS ERDDAP Argo records give longitude and latitude in "
            "degrees_east/degrees_north from satellite position fixes on "
            "WGS84; sea pressure increases downward"
        ),
    ),
    IOOS_GLIDERS.source_id: ModelSourceReference(
        crs="EPSG:4326",
        vertical_positive="down",
        basis=(
            "IOOS Glider DAC profiles give longitude and latitude in "
            "degrees_east/degrees_north from GPS fixes on WGS84 and declare "
            "depth positive down"
        ),
    ),
}

#: Every source's declared references, as the S3 read adapter receives them.
SOURCE_REFERENCES: dict[str, ModelSourceReference] = {
    **MODEL_SOURCE_REFERENCES, **OBSERVATION_SOURCE_REFERENCES}
