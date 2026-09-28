# M2 observation serving: S3 descriptions, S4 resolution, S5 endpoints

Feature:
Observation markers and exact profiles served from the real catalogue, with
each version's semantics resolved from S3 at request time.

Requirements and IMAP refs:
Serving path for IDO-001 to IDO-003 and MOI-001 to MOI-003 (the browser
side is not yet evidenced). IMAP: `s5-observation-response`,
`s5-product-delivery`; supporting `s3-query-contracts`,
`s4-observation-builder`.

Worker branch and commit:
`feature/c4-m2-serving-c` (Agent C): `7b9f4ab` (S3), `0a4bced` (S4),
`1af25ae` (S5). Crosses into Agent A's and Agent B's lanes at the S3→S4
seam; both review it in the review session.

Merge commit:
None. `main` fast-forwarded from `778f31b` to `1af25ae`.

What was implemented:
- S3: `ObservationQuery.list_observation_versions` and
  `describe_observation_version` in the contract, the catalogue adapter and
  the fake. Vertical kind comes from the stored vertical units (decibar is
  pressure, metres are depth; anything else refused). CRS and vertical
  direction come from per-source declarations with their basis, now for the
  INCOIS Argo and IOOS glider sources beside HYCOM (`SOURCE_REFERENCES`).
- S4: observation builders resolve semantics from S3 per request; a fixed
  mapping remains an explicit override. A marker ceiling is checked before
  any profile record is read.
- S5: `GET /api/v1/observation-markers` and `/observation-profiles` with
  `/data` binary routes; synchronous and stateless, since each answer is a
  pure function of its query on an immutable version. The catalogue lists
  observation versions and those it cannot describe. `SERVING_MAX_MARKERS`.

Tests and results:
293 passed, 13 skipped; live PostGIS 27 passed. On the real catalogue:
glider `depth` (m) classified as depth, Argo `PRES` (decibar) as pressure;
15 Argo markers in 598 ms; float 5907085 cycle 32 returns 42 pressure levels
with TEMP 28.92 °C and PSAL 36.05 at the surface and QC flags, in 74 ms;
an unknown cycle is 404 `data_unavailable`.

Deviations or limitations:
- Agent A's fixture stored Argo PRES in metres and Agent B's test labelled
  it depth; both corrected to decibar and pressure.
- QC flag meanings are absent for ERDDAP tabledap imports (the CSV path
  carries no `flag_meanings`); a per-source declaration is needed.
- Building a marker still reads its full profile; the ceiling bounds it.
- The S6 marker layer is on `feature/c3-m1-browser-c` (`d143a19`), held with
  the browser work for review.
