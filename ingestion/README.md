# Ingestion (S2)

Choose a source, choose a dataset, choose variables and ranges, import it,
and hand a validated canonical package to the storage layer.

S2 ends at that handoff. Storage internals -- schema, layout, chunking,
indexing, serving -- belong to S3 and are not implemented here.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r ingestion/requirements.txt
```

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
| `canonical.py` | Coordinate roles and geometry classification |
| `conventions.py` | The checks run before handoff |
| `storage/sink.py` | Development implementations of `StoragePort` |
| `config.py` | Endpoints, locations and limits |
| `web.py`, `static/` | HTTP surface and the minimal UI |

## Sources

| Source | Kind |
|---|---|
| INCOIS ERDDAP | remote, subsets server-side |

Datasets are discovered from the server's published catalogue, filtered to
those this adapter can retrieve. `ErddapServer.datasets` is an optional
allow-list; empty means offer everything.

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
| `INGESTION_DOWNLOAD_ROOT` | Where retrieved files land |
| `INGESTION_BROWSE_ROOTS` | `id=path` pairs the operator may browse |

## Tests

```bash
.venv/bin/python -m pytest ingestion/tests -q
```

## Known limits

- The storage layer does not exist. `StoragePort` is implemented by a
  development sink that writes the package for inspection; it is not durable
  storage and does not pretend to be.
- Imports run in-process. The job model supports long-running imports, but
  execution is synchronous today, and the job store is in memory -- so the
  application must run as a single instance.
- With local sources archived, there is no delimited-text route. ING-001 is
  covered through NetCDF from ERDDAP; **ING-002 and the text half of DIR-007
  are not currently covered**.
- See [conflicts-with-earlier-documents.md](docs/conflicts-with-earlier-documents.md)
  for where this implementation departs from earlier design documents.
