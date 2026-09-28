# S4 execution and S5 point-field serving

Feature:
S4 execution boundary with a bounded local executor, and an S5 request
coordinator, HTTP adapter, wire format and composition point that serve
sampled scalar point-field products.

Requirements and IMAP refs:
S4 owns no SRS requirement. S5 owns BDA-001; this is a partial path toward
it — model products are served, but no catalogue, marker or profile response
exists yet, so BDA-001 is not claimed. IMAP: `s4-execution`,
`s4-local-executor-adapter`, `s5-request-coordinator`, `s5-failure-status`,
`s5-bulk-path`, `s5-product-delivery`, `s5-http-scalar-adapter`.

Worker branch and commit:
`feature/c1-s4-s5-serving` at `28321a5`, then
`fix/c1-effective-budget-work-ceiling` at `0e53eba` (Agent C).

Merge commit:
None. `main` was fast-forwarded from `55ffb6d` to `28321a5`, then to
`0e53eba`.

What was implemented:
- `processing/execution.py` — request, state, result and failure contract;
  `LocalExecutor` with point and cell ceilings, declared capabilities, stable
  failure codes and no leakage of unexpected errors.
- `serving/coordinator.py` — transport-neutral request validation, effective
  point budget (requested, capped at the server ceiling, reduction recorded),
  status and product access.
- `serving/wire.py` — JSON descriptor on the control path; one little-endian,
  eight-byte-aligned binary body on the data path, values in source dtype.
- `serving/http.py` — FastAPI adapter built by factory:
  `POST /api/v1/point-fields`, `GET /api/v1/point-fields/{id}`,
  `GET /api/v1/point-fields/{id}/data`, `GET /api/v1/capabilities`.
- `serving/compose.py` — the only place implementations are chosen;
  `SERVING_MAX_POINTS`, `SERVING_MAX_CELLS`, `SERVING_RETAINED_JOBS`.

Tests and results:
`pytest ingestion/tests processing/tests serving/tests` — 187 passed.
`compileall`, `git diff --check` and `imap check` clean. Smoke test through
uvicorn on `data/raw/model/hycom_glby008_expt930/indian_ocean_ts_sample.nc`
(read-only): 105,600 cells sampled to 20,000 points in under 100 ms; every
delivered value equal to its source cell; budget reduction and work-limit
failure observed.

Deviations or limitations:
- No independent review; the author merged on the owner's standing
  instruction.
- The product builder is supplied by the caller. It is bound to the storage
  read path once `s3-query-contracts` lands; until then no deployable app
  entry exists, and no catalogue endpoint.
- The local executor is synchronous and keeps job state in process: one API
  instance only. A worker executor replaces it through the same contract.
- Masked cells consume the point budget; in the smoke test 37% of delivered
  points were masked land cells.
- The two S5 nodes and one S4 node that were first marked implemented had
  contracts revised during the work; they were returned to in-progress and
  completed against the revised wording.
