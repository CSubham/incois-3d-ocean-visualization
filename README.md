# incois-3d-ocean-visualization
A web-based 3D ocean data visualization platform for exploring and analyzing INCOIS oceanographic datasets. It enables interactive visualization across latitude, longitude, depth, and time, helping users examine spatial patterns, temporal changes, and multi-dimensional marine data through an intuitive 3D interface.

## Start here

**[docs/STATUS.md](docs/STATUS.md)** — what is built, what is not, which
document governs what, and what comes next. Read it before anything else.

## Repository layout

```
docs/            global documentation — system-wide truth
  project/       locked requirements blueprint (SRS)
  architecture/  locked HLSA, and the working LLD
  design/        UI and interaction design (S6/S7, not yet started)
  history/       past decisions and investigations
  tasks/         current work packets
  reviews/       stress tests and readiness reviews
data/            sample datasets, laid out to match the LLD path convention
  raw/model/     gridded model fields
  raw/obs/       point observations
  curated/       written by S2 at runtime
  rejected/      written by S2 at runtime
scripts/         data acquisition scripts
ingestion/       S2 Data Ingestion surface
```

`AGENTS.md` is the canonical agent instruction file; `CLAUDE.md` points at it.

## Authority chain

`docs/project/` holds the locked requirements blueprint. `docs/architecture/`
holds the locked HLSA and the working LLD derived from it. Neither locked
document may be edited, and no document may introduce a requirement the SRS
does not contain.

## Status

The HLSA is locked; the LLD is incomplete and under active revision.
Implementation not yet started. Sample data covering all
eleven S2 requirements is in place — see `data/README.md`.
