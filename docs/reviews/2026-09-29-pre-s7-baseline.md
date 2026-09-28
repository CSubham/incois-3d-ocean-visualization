# Pre-S7 review baseline

Measured on `main` at `f12efe1` before the pre-S7 deviation reviews. Nothing
user-facing proceeds past the S6 renderer until the reviews close.

## Authority for the reviews

- `docs/project/SRS_Technical_Requirements_Mapping.txt` — locked, 39 IDs.
- `docs/architecture/HLSA_...md` — locked stage ownership (View 7).
- `docs/architecture/LLD_...md` — the working copy, decisions D1–D11.
- `docs/history/INCOIS_3D_Ocean_Visualization_Technical_Investigation.md` —
  §C per stage, §D contracts, §F algorithms, §G decision audit.
- Proposed Decision Record entries not yet in Linear: D12 (CesiumJS globe as
  the S6 renderer implementation, departing from LLD D6) and D13 (sampled
  scalar point field as a prototype path).

## Tests

`pytest ingestion/tests processing/tests serving/tests`: 256 passed,
9 skipped (live). With the disposable live database: 19 live and contract
tests pass. Hangs of `test_web.py::test_health` reported by Agents A and B did
not reproduce outside their sandboxes.

## Lint (ruff: pyflakes, bugbear, syntax errors) — 19 findings

- 9 × `zip()` without `strict=`: a length mismatch between scientific
  arrays would truncate silently. `ingestion/query_memory.py:175`,
  `ingestion/storage/postgres.py:223`, `ingestion/storage/query.py:656`,
  `ingestion/tools/delimited.py:84`, `processing/observation.py:482,576`,
  `processing/point_field.py:77`, `serving/wire_observation.py:201`, one test.
- 1 × undefined name `Mapping` in `ingestion/tests/query_support.py:321`.
- 1 × unused local `vert_dims` in `ingestion/canonical.py:122`.
- 8 × unused imports (one, `serving/wire.py:24`, is a deliberate re-export).

## Types (mypy, non-strict, tests excluded) — 35 errors

ingestion 21, processing 3, serving 11. Most are precision: xarray dimension
names typed `Hashable` used as `str`, `Literal` narrowing. Possible real
`None` gaps to confirm or dismiss:
`ingestion/storage/postgres.py:177` (`_signed` on an optional longitude),
`ingestion/adapters/erddap.py:316` (optional epoch),
`ingestion/web.py:92-93` (`Area` from optional bounds),
`ingestion/storage/sink.py:80`, `ingestion/adapters/opendap.py:231`.

## Coverage (unit and live tests together)

Most modules 85–100 %. Lowest: `ingestion/storage/sink.py` 52 %,
`ingestion/adapters/erddap.py` 75 %, `ingestion/conventions.py` 79 %,
`ingestion/storage/query.py` 81 %.

## Stage boundaries

- `processing` imports only the S3 contract (`processing/managed.py`).
- `serving` imports S3 composition only inside `create_default_app`.
- `ingestion` imports no later stage.
- Two composition roots construct storage: `ingestion/composition.py` and
  `ingestion/web.py` (S2's HTTP module builds its own storage inline).

## Known open findings carried in

- Catalogue listing opens every stored object to read coordinates.
- QC flag meanings are not carried by the S3 profile read.
- S3 profile retrieval and the S4 observation builder both extract profile
  values; S4 should consume S3 records.
- No CI; no lint, type or coverage gate runs automatically.
