# Ingestion (S2)

Choose a source, choose a dataset, choose variables and ranges, import it,
and hand a validated canonical package to the storage layer.

S2 ends at that handoff. Storage internals -- schema, layout, chunking,
indexing and serving -- belong to S3. The current application composes S2 with
the first thin S3 implementation: immutable local NetCDF objects plus a
PostgreSQL/PostGIS catalogue and observation-profile index.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r ingestion/requirements.txt
```

Start the development catalogue and apply its schema:

```bash
docker compose up -d
export INGESTION_CATALOGUE_DSN='postgresql://incois:incois@127.0.0.1:5433/incois'
psql "$INGESTION_CATALOGUE_DSN" -f ingestion/storage/schema.sql
```

The default object root is `data/store/`. Override it with
`INGESTION_OBJECT_STORE` when required.

```bash
.venv/bin/python -m uvicorn ingestion.web:app --port 8000
```

Then open <http://127.0.0.1:8000>.

## Architecture

```
UI  →  HTTP layer  →  IngestionService  →  SourcePort  →  adapter
                              ↓
                      canonicalize → validate
                              ↓
                       CanonicalPackage  →  StoragePort
                                                ↓
                         immutable NetCDF object + PostGIS catalogue/profile rows
```

The service resolves a source id to a `SourcePort` and never learns what is
behind it. Adding a source means adding an adapter and one entry in
`adapters/__init__.py`; the workflow does not change.

| Path | Holds |
|---|---|
| `domain/` | `ImportSelection`, `CanonicalPackage`, `ValidationResult`, `ImportJob` |
| `ports.py` | `SourcePort` and `StoragePort` -- the two boundaries |
| `service.py` | The workflow. No source-specific logic. |
| `adapters/erddap.py` | ERDDAP protocol, configured per server |
| `adapters/opendap.py` | Explicitly configured OPeNDAP model datasets |
| `tools/delimited.py` | Registered delimited observation parsing used by tabledap |
| `canonical.py` | Coordinate roles and geometry classification |
| `conventions.py` | The checks run before handoff |
| `storage/objects.py` | Immutable local NetCDF object store and object-store contract |
| `storage/postgres.py` | `StoragePort` implementation for catalogue, variables and profiles |
| `storage/schema.sql` | PostgreSQL/PostGIS catalogue and spatial indexes |
| `storage/sink.py` | Development and test implementations of `StoragePort` |
| `config.py` | Endpoints, locations and limits |
| `web.py`, `static/` | HTTP surface and the minimal UI |

## Sources

| Source | Kind |
|---|---|
| INCOIS ERDDAP | Four depth-resolved temperature/salinity grids plus Argo observations; subsets server-side |
| IOOS Glider DAC | Four curated `ru29` Indian Ocean and Bay of Bengal deployments; subsets server-side |
| HYCOM archive | GLBy0.08 model temperature, salinity and currents over OPeNDAP |

ERDDAP datasets are discovered from the server's published catalogue and
filtered through a curated allow-list. `ErddapServer.datasets` is optional;
empty means offer everything the adapter can retrieve. OPeNDAP datasets are
named explicitly in configuration rather than inferred from a whole THREDDS
catalogue.

Local file sources (NetCDF, CSV/text, folder) are archived in
[`archive/local-sources/`](../archive/local-sources/README.md) and are not
part of the running application.

## Dataset shapes

Datasets are classified, not flattened: `grid`, `profile`, `trajectory`,
`trajectory_profile`, `point`. A declared CF `featureType` is honoured; where
one is absent the shape is inferred from structure, and a dataset that cannot
be classified is reported rather than guessed.

## Validation

Nine checks run before anything is handed on -- variables present, dimensions
valid, latitude/longitude/time/depth identifiable, units declared, fill values
applied, values present, shape classified. A dataset that fails is reported
with the reason and never reaches storage.

## Configuration

| Variable | Sets |
|---|---|
| `INCOIS_ERDDAP_URL` | ERDDAP endpoint |
| `INCOIS_MAX_REQUEST_VALUES` | Guard on remote request size |
| `IOOS_GLIDER_URL` | IOOS Glider DAC ERDDAP endpoint |
| `HYCOM_URL` | HYCOM OPeNDAP dataset endpoint |
| `HYCOM_MAX_REQUEST_VALUES` | Guard on HYCOM request size |
| `INGESTION_OBJECT_STORE` | Root for immutable stored NetCDF objects |
| `INGESTION_CATALOGUE_DSN` | PostgreSQL/PostGIS catalogue connection string |
| `INGESTION_DOWNLOAD_ROOT` | Where retrieved files land |

## Tests

```bash
.venv/bin/python -m pytest ingestion/tests -q
```

Current result: **109 passed**. These tests cover the local object store,
storage derivation logic and the S2-to-S3 contract, but do not connect to a
live PostgreSQL/PostGIS instance.

## Known limits

- PostgreSQL/PostGIS persistence is runtime-wired, but a clean-database
  end-to-end import, query and read-back still needs to be recorded as
  integration evidence.
- The implemented array backend stores immutable NetCDF on the local
  filesystem. A deployment object-store adapter and any chunked visualization
  derivative remain unselected until representative access patterns are
  measured.
- Imports run in-process. The job model supports long-running imports, but
  execution is synchronous today, and the job store is in memory -- so the
  application must run as a single instance.
- No configured source currently supplies chlorophyll. CTD and BGC records can
  use the tabledap path, but curated datasets are not registered yet.
- The application is local only; S4 processing, the S5 visualization API and
  S6/S7 visualization are not built.
- See [conflicts-with-earlier-documents.md](docs/conflicts-with-earlier-documents.md)
  for where this implementation departs from earlier design documents.
