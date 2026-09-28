# S5 deployable entry point, catalogue and retention fix

Feature:
Binds S5 to the real S3 reads through one composition function, adds the
model catalogue endpoint, and fixes job retention order.

Requirements and IMAP refs:
Partial path toward BDA-001 (catalogue and model products served; marker and
profile responses remain). IMAP: `s5-catalogue-response`,
`s5-http-scalar-adapter`, `x-control-bulk`; `s4-local-executor-adapter`
(retention fix).

Worker branch and commit:
`feature/c3-m1-browser-c` (Agent C): `781af50`, `d619007`, `c9d9a98`,
re-applied onto `f96e220` as `468712f`, `12170de`, `f482c8d`. The branch's
browser commits are held until the visual review.

Merge commit:
None; cherry-picked onto `main`.

What was implemented:
- `processing/managed.py`: the S3→S4 handoff is the executor's product
  builder, passes the work ceiling, and maps S3 read failures to
  `variable_unavailable` or `data_unavailable`.
- `serving/compose.py:create_default_app` — deployable entry point:
  `uvicorn serving.compose:create_default_app --factory`, configured only by
  environment; serves a built browser app from the same origin if present.
- `GET /api/v1/catalogue`: versions with exact times and depths, plus
  versions S3 could not read and why.
- Request times accept any ISO 8601 offset and are converted to UTC;
  refusing offsets made the catalogue's own `+00:00` times unusable. "NaT"
  is rejected.
- Job retention follows submission order (Agent B review finding); a job
  evicted while running is not re-inserted when it finishes.

Tests and results:
256 passed, 9 skipped; live PostGIS 19 passed. End to end on a HYCOM Bay of
Bengal import (80–92E, 5–21N, 0–1000 m): 1,998,183 cells sampled to 200,000
points in 790 ms with no storage detail in any response.

Deviations or limitations:
- No independent review of these three commits; Agent B reviewed their
  predecessors and raised the two fixed findings.
- The catalogue listing opens every stored object to read coordinates.
