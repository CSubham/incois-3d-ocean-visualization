# C5 H2 observation failure semantics

Feature:
Expected observation outcomes now cross the shared S4 execution boundary with
stable codes and explicit S5 HTTP semantics. A valid marker search with no
matching profiles is delivered as a zero-count marker product rather than a
failure.

Requirements and IMAP refs:
This closes H2 from the S3–S5 deviation review for
`s4-observation-builder`, `s5-observation-response`, and
`x-contract-tests`. IMAP was inspected read-only and was not changed.

What was implemented:
- The shared processing failure map classifies exact-profile identity,
  requested-variable, invalid-observation, and all-missing failures as
  `profile_not_found`, `variable_unavailable`, `invalid_observation`, and
  `all_missing` in specificity order.
- S3 `ProfileNotFound` retains its exact not-found meaning at the S4 boundary;
  other S3 read failures remain `data_unavailable`.
- An empty S3 marker search produces an immutable marker product with zero
  markers, zero counts, the S3-declared vertical coordinate and units, and a
  valid empty binary representation.
- The S5 observation status table exhaustively maps invalid requests to 400,
  not-found or unavailable requests to 404, unprocessable scientific products
  to 422, and only unexpected internal failures to 500.

Tests and results:
Focused S4 execution, managed-observation, observation-wire, and S5 HTTP tests
cover every typed observation failure plus the empty marker result. The final
stage suites and merge-gate checks are recorded in the handoff.

Deviations or limitations:
- An empty result has no profile record from which to obtain a source time
  coordinate name or encoding. Its marker metadata therefore uses the S3
  record-contract role name `time` and explicitly null encoding fields; it
  retains the version-level vertical name, units, CRS, direction, and
  provenance without inference.
