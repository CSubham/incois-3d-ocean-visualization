# Where the project stands

One page. If it disagrees with the code, the code is right and this needs fixing.

Reviewed against commit `3121909`, 27 September 2026.

---

## The seven stages

| Stage | State | Where |
|---|---|---|
| S1 Sources | External. Not ours to build. | — |
| **S2 Ingestion** | **Complete.** All 11 requirements it owns are covered, one partly. | `ingestion/` |
| **S3 Storage** | **Implemented, integration proof pending.** Immutable local NetCDF objects plus a PostgreSQL/PostGIS catalogue and observation-profile index are runtime-wired. | `ingestion/storage/` |
| S4 Processing | Not started | — |
| S5 Backend | Not started | — |
| S6 Rendering | Not started | — |
| S7 Interface | Not started | — |

S2 has its own operator interface for choosing what to import. **That is not S7.** S7 is the visualization.

## Chosen sequence

**S2 first, completed. Prove the thin S3 implementation against a clean live
database, then build a thin visualization path.**

The earlier plan was to leave S2 half done and go straight to S3, because a
model-only visualization is demonstrable against a deadline. That was
reversed: closing S2 turned out to be one adapter path plus one source, not
weeks, and the first S3 implementation now stores both gridded arrays and
observation/profile records rather than requiring a later schema rewrite.

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

**Built, but thin**

- **S3 persistence.** `PostgresStorage` is the active `StoragePort`. It writes
  arrays through `LocalObjectStore` and records dataset versions, variables and
  observation profiles through `storage/schema.sql`. The local object path and
  derivation logic are tested; a clean live PostgreSQL/PostGIS import and
  read-back has not yet been recorded as evidence.
- **Job lifecycle.** The model supports background execution; execution is synchronous and in-memory, so the app must run as one instance and progress cannot be live.
- **The operator UI.** Functional, deliberately unpolished.

**Not built**

- S4 processing, the S5 visualization API, S6 rendering and S7 visualization UI.
- Authentication — by decision, to be platform-level at deploy.
- Deployment. Local only.

The current automated suite is **109 passed**. It does not connect to a live
PostgreSQL/PostGIS instance.

---

## Known limits

- **S3 still needs a live integration proof.** The code and schema exist and
  are runtime-wired, but a clean-database model import, observation import,
  catalogue query and array read-back have not been captured together.
- **Local NetCDF is the only implemented array backend.** Chunked visualization
  derivatives and a deployment object-store adapter remain evidence-gated.
- **Single instance only.** In-memory job store.
- **Not deployed.**
- **No chlorophyll** from any current source.

## Next

1. **Prove S3 end to end** — initialize a clean PostGIS catalogue, import one
   gridded field and one observation dataset, then verify the stored arrays,
   catalogue rows, spatial profile lookup and stable references.
2. **Benchmark the visualization read pattern** — region, time, depth and
   volume access on representative data before choosing a chunked derivative.
3. **Build a thin visualization path** — enough of S4/S5/S6/S7 to show one
   field in 3D with float markers and one selected profile.
