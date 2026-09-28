# S3 model-field query and S3→S4 handoff

Feature:
Deployment-neutral S3 read contract for model catalogue and scalar fields,
an in-memory and a PostgreSQL/object-store implementation, one composition
root, and the S3→S4 handoff into the point-field path.

Requirements and IMAP refs:
S3 and S4 own no SRS requirement. IMAP: `s3-query-contracts` (model and
catalogue portion), `s3-model-field-query-adapter`, `s3-live-proof`.

Worker branch and commit:
`feature/c2-s3-query-handoff-a` at `ab0b3a8` (Agent A), re-applied onto
`d23f936` as `d5b17cc` with authorship kept. Reviewed by Agent C.

Merge commit:
None. `main` was fast-forwarded from `d23f936` to `d5b17cc`.

What was implemented:
`ingestion/query.py` contract (no storage or psycopg imports),
`ingestion/query_memory.py` fake, `ingestion/storage/query.py` catalogue
adapter (read-only SQL, lazy open through ObjectStore, CRS and vertical
direction from CF or an explicit per-source declaration with its basis,
otherwise refused; no SQL, DSN or path in values or errors),
`ingestion/composition.py` (`S3_QUERY_BACKEND=catalogue|memory`),
`processing/managed.py` handoff, shared contract tests.

Tests and results:
211 passed, 7 skipped (live, no DSN) on the combined tree. With
`INGESTION_CATALOGUE_DSN` on the disposable `incois_s3_query_live_test`
database: 15 passed — real HYCOM water_temp and INCOIS Argo imported into a
clean PostGIS, read back, found spatially, and passed through S4.

Deviations or limitations:
- Catalogue exposes depth and time counts, not values; a client cannot yet
  name an exact source time from it. To be closed in M1 integration.
- One malformed catalogue version fails the whole listing.
- Provenance strings containing "/" are dropped without disclosure.
- The handoff is not yet a `ProductBuilder`, does not pass
  `maximum_cells`, and does not translate S3 errors; M1 integration.
- Marker lookup and exact-profile reads are not in the contract (M2).
