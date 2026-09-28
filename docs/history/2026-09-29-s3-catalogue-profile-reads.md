# S3 catalogue values, marker search and exact profile reads

Feature:
Completes the S3 read contract: exact model time and depth values in the
catalogue, unavailable-version reporting, typed marker search and exact
profile retrieval, with in-memory and PostgreSQL/PostGIS implementations.

Requirements and IMAP refs:
S3 owns no SRS requirement; these reads serve IDO-001 to IDO-003 and
UIC-001 to UIC-003 downstream. IMAP: `s3-query-contracts`.

Worker branch and commit:
`feature/c3-s3-reads-a` at `bc7007d` (Agent A), based on `b3aa63d`.
Reviewed by Agent C.

Merge commit:
None. Agent B's observation work (`36c8d00`, `000d0e7`) reached `main`
first, so `bc7007d` was re-applied on top as `364dd5f` with authorship kept;
the two touch no common file.

What was implemented:
`DatasetVersionListing` (a sequence of summaries plus `unavailable` with
reasons); `time_values` and `depth_values` on each summary; provenance keeps
strings containing "/" and marks real withheld values with `_withheld`;
`ProfileSearch`, `ProfileMarker`, `ProfileIdentity`, `ObservationProfile`
with values, units, QC and timestamps, and `ProfileNotFound`.

Tests and results:
Combined tree with Agent B's work: 240 passed, 9 skipped (live). On the disposable
`incois_s3_query_live_test` database: 19 passed, including a real INCOIS
Argo marker (platform 7902250, cycle 12) and its exact TEMP/PSAL profile.

Deviations or limitations:
- Listing opens every stored object to read coordinates; record them at
  import time before the catalogue grows.
- QC flag meanings (`flag_values`, `flag_meanings`) are not carried.
- S3 profile retrieval now overlaps the S4 observation profile builder;
  in M2 the S4 builder consumes these records instead of re-decoding.
- The reported `test_web.py::test_health` hang did not reproduce outside the
  agent's sandbox (216 passed in 2.2 s).
