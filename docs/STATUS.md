# Where the project stands

One page. If it disagrees with the code, the code is right and this needs fixing.

Commit `1deae5f`, 20 September 2026.

---

## The seven stages

| Stage | State | Where |
|---|---|---|
| S1 Sources | External. Not ours to build. | — |
| **S2 Ingestion** | **Built.** 79 tests. Two sources. | `ingestion/` |
| S3 Storage | **Next.** Nothing persists today. | — |
| S4 Processing | Not started | — |
| S5 Backend | Not started | — |
| S6 Rendering | Not started | — |
| S7 Interface | Not started | — |

S2 has its own operator interface for choosing what to import. **That is not S7.** S7 is the visualization.

## Chosen sequence

Deadline-driven: **S3 storage, then a thin visualization path, then observations.**

The alternative was observations first, on the argument that S3 designed against gridded data alone will need rework when profiles arrive. That argument is sound and the risk is real — it is accepted deliberately, because a model-only visualization is demonstrable and observations with nothing to display them in are not.

**What this costs:** `CanonicalPackage` models five geometries and only `grid` has travelled the full path. S3 will be designed against arrays, and the observation/profile side of it — PostGIS, profile records — will be added later rather than designed in. Budget for that.

---

## Requirement coverage

Honest. "Covered" means there is a working path with evidence, not that the code mentions it.

| ID | State | Evidence | Caveat |
|---|---|---|---|
| DIR-001 model outputs | **Covered** | HYCOM GLBy0.08 over OPeNDAP, `source: HYCOM archive file` | Only since the OPeNDAP adapter. The INCOIS products are objective analyses of observations, not model runs. |
| DIR-002 T, S, currents, chlorophyll | **3 of 4** | `water_temp`, `salinity`, `water_u`, `water_v` | **No chlorophyll.** HYCOM is physical, not biogeochemical. Needs a BGC model or BGC-Argo — open decision 5. |
| DIR-003 depths, grids, time steps | **Covered** | 40 levels to 5000 m; 4251 × 4500 global; 16,809 time steps | HYCOM spans 80°S–90°N, so the southernmost ~10° is absent. |
| DIR-004 Argo & Glider | **Not covered** | — | No observation route at all. |
| DIR-005 Argo, Glider, CTD, BGC | **Not covered** | — | Same. |
| DIR-006 observation attributes | **Not covered** | — | Same. |
| DIR-007 NetCDF and delimited text | **Half** | NetCDF via both adapters | Delimited-text parsing archived. |
| ING-001 NetCDF parsing | **Covered** | `adapters/erddap.py`, `adapters/opendap.py`, xarray | |
| ING-002 delimited-text parsing | **Not covered** | — | Archived with the local adapters. |
| STD-001 CF Conventions | **Covered** | `conventions.py`, nine checks; CF `standard_name` used for discovery | Checks are structural. Full IOOS compliance checking is not run. |
| EXT-001 new sources, minimal change | **Covered, with evidence** | Adding OPeNDAP — an entirely new protocol — changed only a new adapter, its registration and config. `ports.py`, `service.py`, `canonical.py`, `conventions.py` and `domain/package.py` were untouched. | |

**39 requirement IDs exist. The 11 above are the ones S2 touches.** The rest belong to S4–S7 and are untouched by definition.

### Not covered, counted honestly

Five requirements have no path: DIR-004, DIR-005, DIR-006, ING-002, and half of DIR-007 — all observations and delimited text. Plus chlorophyll within DIR-002.

---

## Sources

| Source | Protocol | Offers | In scope because |
|---|---|---|---|
| **HYCOM** | OPeNDAP | 1 dataset — GLBy0.08 global analysis | Genuine model output: T, S, currents, 40 depth levels |
| **INCOIS ERDDAP** | ERDDAP griddap | **4** of its 15 | The four depth-resolved T/S analyses |

INCOIS's other 11 are two-dimensional satellite surface products — SST, scatterometer winds, Oceansat — outside DIR-001 to DIR-003. They are excluded by an allow-list in `config.py`, not hidden by accident.

---

## What is built properly, and what is not

**Properly built and proven**

- The port boundary. A new protocol needed no change to the core — demonstrated, not asserted.
- Geometry classification. Five shapes, CF `featureType` honoured, unclassifiable data reported rather than guessed.
- Validation. Nine checks; a dataset without units is refused and never reaches storage.
- Size guards. OPeNDAP retrieval is lazy, so a whole-globe request was refused at 2.9 trillion values with nothing transferred.
- Coordinate conventions. 0–360 and −180–180 both handled; edge-crossing named rather than silently wrong.

**Built, but thin**

- **Storage handoff.** Proven architecturally — a complete package crosses `StoragePort` — against a development sink. Not persistence.
- **Job lifecycle.** The model supports background execution; execution is synchronous and in-memory, so the app must run as one instance and progress cannot be live.
- **The operator UI.** Functional, deliberately unpolished.

**Not built**

- Everything downstream of S2.
- Any route to observation data.
- Authentication — by decision, to be platform-level at deploy.
- Deployment. Local only.

---

## Known limits

- **S3 does not exist.** Every import evaporates.
- **Single instance only.** In-memory job store.
- **Not deployed, and not pushed.** Nine commits on one machine.
- **No chlorophyll** from any current source.

## Next

1. **Push.** Nine commits exist in one place.
2. **S3, thin** — object store plus catalogue, designed against gridded data with the profile side deferred knowingly.
3. **A thin visualization path** — enough of S4/S5/S6 to show one HYCOM field in 3D.
4. **Observations** — tabledap adapter, closing five requirements.
