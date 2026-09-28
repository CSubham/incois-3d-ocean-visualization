# S3 catalogue coordinate and profile QC follow-ups

Feature:
Stores exact model time and depth axes in the S3 catalogue at import, while
retaining object-read fallback for older rows, and carries source QC vocabulary
metadata on exact observation-profile reads.

Requirements and IMAP refs:
S3 owns no SRS requirement. This work closes follow-ups under
`s3-query-contracts`, `s3-model-field-query-adapter`,
`s3-catalogue-profile-store`, and `s3-live-proof` without changing their
moderator-owned IMAP state.

Worker branch and implementation commit:
`feature/c4-s3-followups-a` at `5c95678` (Agent A), rebased onto `0bdef47`
after non-overlapping processing and serving work reached `main`.

What was implemented:
- `dataset_version.time_values` and `depth_values` hold exact axes for new
  gridded imports; nullable columns preserve existing catalogue rows.
- Model-version listing and description use those catalogue values without
  opening scientific objects. Rows predating the columns retain the previous
  managed-object fallback.
- Exact observation profiles expose QC `flag_values`, `flag_meanings`, and
  `conventions`; each missing source attribute is represented as `None`.
- The web unit fixture now uses the existing recording sink, keeping unit tests
  independent of a developer database.

Tests and results:
- Focused storage/query unit tests: 37 passed, 9 deselected.
- Disposable PostgreSQL/PostGIS live contract suite: 9 passed, 10 deselected.
- Active ingestion, processing, and serving unit suites after rebasing: 259 passed,
  10 deselected.

Deviations or limitations:
- Existing rows with either catalogue coordinate array absent open the managed
  object to recover both axes; the row is not mutated during a read.
- Observation/profile imports keep their dense coordinate arrays in the
  managed object and leave the two model-axis catalogue columns null.
