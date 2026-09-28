# S4 sampled scalar point field

Feature:
Pure S4 subsetter and sampled scalar point-field builder, producing a
renderer-independent product envelope from a decoded rectilinear grid.

Requirements and IMAP refs:
S4 owns no SRS requirement (HLSA View 7). This is preparation toward partial
MVR-001 and the temperature path of MVR-006, which only an S6 browser view
can evidence; this merge evidences neither. IMAP: `s4-subsetter`,
`s4-sampled-scalar-builder`, `s4-product-envelope`, under
`x-point-field-prototype-gate`.

Worker branch and commit:
`feature/c1-s4-scalar-field-b` at `d03fb86` (Agent B), then
`fix/c1-s4-envelope-integrity` at `df69b5a` (review fixes, Agent C).

Merge commit:
None. `main` was fast-forwarded from `3121909` to `df69b5a`.

What was implemented:
`processing/` — exact-index subsetting of one variable at one time within
inclusive area and depth bounds; deterministic evenly spaced sampling in
index space under a point budget, with no interpolation, aggregation or
smoothing; a product carrying dataset and version identity, declared CRS and
vertical direction, coordinate names, units, dtypes and time encoding, an
identity coordinate transform, mask semantics, sampling policy and
parameters, selected indices, cell and valid-value counts, full-subset and
delivered ranges, and JSON-compatible provenance. Typed failures for invalid
requests, variables, times, grids, empty and all-missing subsets.

Tests and results:
`pytest ingestion/tests processing/tests` — 145 passed (109 ingestion,
36 processing). `compileall`, `git diff --check` and `imap check` clean.

Deviations or limitations:
- Merged on the owner's instruction before the D10 point-field entry was
  recorded in the Linear Decision Record, and without a review of `df69b5a`
  independent of its author. Both remain owed.
- The LLD lists no point-field builder; D10 is to record that departure.
- No S3 read contract exists yet; callers supply the decoded dataset and the
  descriptor, including a CRS that is not checked against the source.
- Masked cells are eligible for sampling, so a sample can deliver no valid
  value while the subset has some. Values under the mask are delivered as
  stored and are declared non-scientific.
- The product is sampled points, not a volume, slice or isosurface.
