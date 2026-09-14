# Data layout

The directory structure mirrors the path convention in the LLD (S1 Data Sources,
S2 Data Ingestion, S3 Data Storage), so the local development layout matches the
deployed share and the same relative paths work in both.

```
data/
  raw/          files as they arrive, never modified in place
    model/      gridded fields, one directory per feed
    obs/        point observations, one directory per feed
  curated/      S2 writes canonical CF NetCDF here
  rejected/     S2 moves files that fail CF or dimension checks here, with a reason
```

Every data file has a `.json` sidecar next to it recording the source URL, the exact
request, the spatial and temporal bounds, value ranges and valid-value counts. The
sidecar is the provenance record; do not separate it from its data file.

## raw/model — gridded fields

| Directory | Source | Contents |
|---|---|---|
| `hycom_glby008_expt930/` | HYCOM + NCODA Global 1/12° (`tds.hycom.org`) | `water_temp`, `salinity`, `water_u`, `water_v`, 20 depth levels 0–4000 m. `timeseries/` holds 4 consecutive daily steps for DIR-003 and later MVR-005 |
| `incois_argo_10d_vam/` | INCOIS ERDDAP | Gridded Argo analysis, `TEMP`/`SAL`, 19 levels. A gridded *analysis*, not a model and not point observations — it has no individual floats, so it cannot serve IDO-002 |
| `incois_valueadded_currents/` | INCOIS ERDDAP | **Defective. Retained only as a reject-branch fixture.** See `known_defect` in its sidecar |

## raw/obs — point observations

| Directory | Source | Contents |
|---|---|---|
| `incois_argo_floats/` | INCOIS ERDDAP tabledap | 12 floats, 2,929 rows. `TEMP`/`TEMP_ADJUSTED` pairs encode real-time vs delayed-mode (DIR-004) |
| `argo_bgc_synthetic/` | Argo GDAC via Ifremer ERDDAP | 8 BGC floats, 16,108 rows, `chla` in mg/m³ — the only chlorophyll source |
| `ioos_glider_ru29/` | IOOS Glider DAC | Slocum glider, Bay of Bengal, 42 dive profiles to 960 m |
| `goship_i07n_ctd/` | CCHDO GO-SHIP line I07N, R/V Ronald H. Brown | Standalone ship CTD casts. 12 stations in box, Arabian Sea, ~1 dbar resolution to 3860 dbar. Provider SHA256 verified; file kept unmodified |

## Notes for ingestion

Four different QC vocabularies arrive here, which is a deliberate test of the
Source Registry and EXT-001:

- core Argo — `*_ADJUSTED` plus `*_QC` flags
- BGC-Argo — `chla_adjusted`, same convention, different variable set
- IOOS glider — QARTOD flags (`qartod_*_primary_flag`)
- GO-SHIP CTD — WOCE flags in `*_qc` (`standard_name: status_flag`)

Two NetCDF generations also arrive: NetCDF-3 classic (HYCOM, INCOIS) and NetCDF-4/HDF5
(GO-SHIP). The reader must handle both.

Delayed-mode supersession for Argo keys on `PLATFORM_NUMBER` + `CYCLE_NUMBER` + `PRES`:
prefer the `_ADJUSTED` value where populated, fall back to the raw value where not.

`curated/` and `rejected/` are empty by design and are written by S2 at runtime.
