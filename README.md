# incois-3d-ocean-visualization
A project for a web-based 3D ocean data visualization platform for exploring
and analysing oceanographic model fields alongside instrument observations.
The completed system will support interactive views across latitude,
longitude, depth and time; the current implementation status is recorded
below.

## Start here

**[docs/STATUS.md](docs/STATUS.md)** — what is built, what is not, which
document governs what, and what comes next. Read it before anything else.

## Repository layout

```
docs/            global documentation — system-wide truth
  project/       locked requirements blueprint (SRS)
  architecture/  locked HLSA, and the working LLD
  design/        UI and interaction design (S6/S7)
  history/       past decisions and investigations
  tasks/         current work packets
  reviews/       stress tests and readiness reviews
data/            scientific fixtures and local runtime data
  raw/model/     protected gridded model fixtures with provenance sidecars
  raw/obs/       protected observation fixtures with provenance sidecars
  acquired/      data retrieved by operator acquisition workflows
  store/         local immutable NetCDF objects written by the thin S3 binding
  curated/       reserved for a local accepted-data adapter
  rejected/      retained rejection fixtures or evidence
scripts/         data acquisition scripts
ingestion/       S2 ingestion plus the first thin S3 storage binding
processing/      S4 bounded scientific product builders
serving/         S5 API, wire formats and operational endpoints
docker-compose.yml  development PostgreSQL/PostGIS catalogue
```

`AGENTS.md` is the canonical agent instruction file; `CLAUDE.md` points at it.

## Authority chain

`docs/project/` holds the locked requirements blueprint. `docs/architecture/`
holds the locked HLSA and the working LLD derived from it. Neither locked
document may be edited, and no document may introduce a requirement the SRS
does not contain.

## Status

The SRS and HLSA are locked; the LLD is incomplete and under active revision.
S2 ingestion is complete. S3 has an immutable local object store, a
PostgreSQL/PostGIS catalogue and recorded live-database proof. Bounded S4
products and their S5 delivery paths are implemented for the current
prototype. S6/S7 browser work exists on feature branches but is not yet part
of `main`. See [docs/STATUS.md](docs/STATUS.md) for evidence and the current
next steps.
