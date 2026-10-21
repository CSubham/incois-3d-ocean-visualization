# Where the project stands

One page. If it disagrees with the code, the code is right and this needs fixing.

Reviewed against `main` at `8864256` and the named active feature branches,
21 October 2026.

---

## The seven stages

| Stage | State | Where |
|---|---|---|
| S1 Sources | External. Not ours to build. | — |
| **S2 Ingestion** | **Complete.** All 11 requirements it owns are covered, one partly. | `ingestion/` |
| **S3 Storage** | **Implemented and live-proven.** Immutable local NetCDF objects plus a PostgreSQL/PostGIS catalogue and observation-profile index are runtime-wired. | `ingestion/storage/` |
| **S4 Processing** | **Prototype paths implemented.** Bounded scalar point fields, depth slices, observation markers and exact profiles are on `main`; volume, isosurface and general grid transforms remain open. | `processing/` |
| **S5 Backend** | **Prototype paths implemented.** Catalogue, scalar point-field, marker and exact-profile delivery plus operational probes are on `main`; the depth-slice encoder is not yet runtime-bound. | `serving/` |
| **S6 Rendering** | **Active feature-branch work.** The reviewed Cesium point-field and observation implementation is not yet merged into `main`; slice and vector work continues on C7 branches. | `feature/c3-m1-browser-c`, C7 branches |
| **S7 Interface** | **Active feature-branch work.** Selection, display, failure and profile UI exists with the S6 branch but is not yet merged into `main`. | `feature/c3-m1-browser-c`, C7 branches |

S2 has its own operator interface for choosing what to import. **That is not S7.** S7 is the visualization.

## Chosen sequence

**S2 and the thin S3 path are complete and proven. Finish review and integration
of the branch-based S6/S7 prototype, then deploy the bounded path.**

The earlier plan was to leave S2 half done and go straight to S3, because a
model-only visualization is demonstrable against a deadline. That was
reversed: closing S2 turned out to be one adapter path plus one source, not
weeks. S3 now stores both gridded arrays and observation/profile records, and
the first bounded S4/S5 product paths are on `main`.

---

## Requirement coverage

Honest. "Covered" means a working path with evidence, not that the code
mentions it.

| ID | State | Evidence | Caveat |
|---|---|---|---|
| DIR-001 model outputs | **Covered** | HYCOM GLBy0.08 over OPeNDAP, `source: HYCOM archive file` | The INCOIS products are objective analyses, not model runs; HYCOM is what closed this. |
| DIR-002 T, S, currents, chlorophyll | **3 of 4** | `water_temp`, `salinity`, `water_u`, `water_v` | **No chlorophyll.** HYCOM is physical, not biogeochemical. Open decision 5. |
| DIR-003 depths, grids, time steps | **Covered** | 40 levels to 5000 m; 4251 × 4500; 16,809 steps | HYCOM spans 80°S–90°N. |
| DIR-004 Argo & Glider | **Covered** | Argo via INCOIS tabledap, 1259 rows; gliders via IOOS ru29, 1014 rows | Both verified against live endpoints. |
| DIR-005 Argo, Glider, CTD, BGC | **Covered for Argo and Glider** | As above | CTD and BGC need further curated datasets — the adapter handles them, no source is registered. |
| DIR-006 observation attributes | **Covered** | lat, lon, depth, time, temperature, salinity, with QC flags and platform identifiers preserved | Chlorophyll, as DIR-002. |
| DIR-007 NetCDF and delimited text | **Covered** | NetCDF via griddap and OPeNDAP; delimited via tabledap CSV | |
| ING-001 NetCDF parsing | **Covered** | `adapters/erddap.py`, `adapters/opendap.py`, xarray | |
| ING-002 delimited-text parsing | **Covered** | `tools/delimited.py`, units taken from the catalogue rather than inferred | |
| STD-001 CF Conventions | **Covered** | `conventions.py`, nine checks; CF `standard_name` used for discovery | Structural. Full IOOS compliance checking is not run. |
| EXT-001 new sources, minimal change | **Covered, with evidence** | Adding OPeNDAP — an entirely new protocol — changed only a new adapter, its registration and config. `ports.py`, `service.py`, `canonical.py`, `conventions.py` and `domain/package.py` untouched. | |

**39 requirement IDs exist. The 11 above are the ones S2 owns.** The rest
belong to S4–S7.

### What remains open in S2

- **Chlorophyll.** No registered source produces it. Needs a biogeochemical
  model or BGC-Argo — open decision 5.
- **CTD and BGC sources.** The tabledap path reads them; no dataset is
  registered. Config, not code.

---

## Sources

| Source | Protocol | Offers | In scope because |
|---|---|---|---|
| **HYCOM** | OPeNDAP | 1 dataset — GLBy0.08 global analysis | Genuine model output: T, S, currents, 40 depth levels |
| **INCOIS ERDDAP** | griddap + tabledap | **5** of its 16 | Four depth-resolved T/S analyses, plus Argo float profiles |
| **IOOS Glider DAC** | tabledap | **4** of its 999 | The ru29 missions, which crossed the Indian Ocean and Bay of Bengal |

Every source is curated by an allow-list. A catalogue lists everything a
centre publishes; this system offers what answers the problem statement.

INCOIS's other 11 are two-dimensional satellite surface products — SST, scatterometer winds, Oceansat — outside DIR-001 to DIR-003. They are excluded by an allow-list in `config.py`, not hidden by accident.

---

## What is built properly, and what is not

**Properly built and proven**

- The port boundary. A new protocol needed no change to the core — demonstrated, not asserted.
- Geometry classification. Five shapes, CF `featureType` honoured, unclassifiable data reported rather than guessed.
- Validation. Nine checks; a dataset without units is refused and never reaches storage.
- Size guards. OPeNDAP retrieval is lazy, so a whole-globe request was refused at 2.9 trillion values with nothing transferred.
- Coordinate conventions. 0–360 and −180–180 both handled; edge-crossing named rather than silently wrong.
- The local scientific object store. Writes are atomic and immutable; stored
  NetCDF can be opened again, path escape is rejected and overwrite is refused.
- Storage shape logic. Dataset extents and signed longitude footprints are
  derived, observation rows are grouped by exact platform/cycle identity, and
  gridded fields do not invent instrument records.
- Clean PostgreSQL/PostGIS proof. Migrations, gridded and observation imports,
  catalogue queries, spatial marker lookup and exact profile read-back were
  exercised against the live catalogue.
- Bounded prototype paths. Scalar point fields, observation markers and exact
  profiles run through S4/S5; depth slices have an S4 builder and S5 wire
  encoder but are not yet bound into the deployed app. Scientific context is
  preserved through self-describing wire formats and coded failures.
- Deployment baseline. The backend has versioned migrations, liveness and
  readiness probes, structured request logs, an unprivileged image and CI
  gates.

**Built, but thin**

- **S3 persistence.** `PostgresStorage` is the active `StoragePort`. It writes
  arrays through `LocalObjectStore` and records dataset versions, variables and
  observation profiles through versioned migrations. The object backend is
  still local-filesystem only.
- **Job lifecycle.** S2 execution is synchronous and in-memory. S4 has a bounded
  local executor, not a durable distributed worker transport.
- **The operator UI.** Functional, deliberately unpolished.

**Not built**

- Full-volume and isosurface products and rendering, time-step animation, OGC
  proof and a cloud object-store adapter.
- S6/S7 in `main`; the browser implementation remains on feature branches.
- Authentication — by decision, to be platform-level at deploy.
- A public deployment. The repository provides an image and deployment notes,
  but no cloud resource has been provisioned.

The latest recorded backend validation is **343 passed with live PostGIS**,
excluding external-provider network tests. The browser branch separately
records tests, type-check and production-build success.

---

## Known limits

- **Local NetCDF is the only implemented array backend.** Chunked visualization
  derivatives and a deployment object-store adapter remain evidence-gated.
- **S2 is single-instance.** Its job store is in memory.
- **Branch integration remains.** The current-vector and browser work must be
  reviewed and merged before a deployable full-stack revision exists.
- **Not deployed.**
- **No chlorophyll** from any current source.

## Next

1. **Integrate the active visualization branches** after review and resolve the
   recorded S6 findings without weakening scientific or resource checks.
2. **Choose the deployment object path**: mount persistent storage for the
   current local adapter or implement the approved object-store adapter.
3. **Run the full-stack deployment gate**: migrations, readiness, bounded model
   field, observation markers, exact profile, browser build and same-origin API
   routing on the target cloud environment.
