# S4 observation execution and depth slices

Feature:
S4 observation product builders now consume the immutable `ProfileMarker` and
`ObservationProfile` records exposed by S3. Typed `ProductBuilder` bindings in
`processing/managed.py` connect marker, exact-profile, scalar point-field and
depth-slice products to their configured S3 query boundaries. A new depth-slice
product and wire encoder deliver either an exact source level or explicitly
requested linear depth interpolation.

Requirements and IMAP refs:
This is implementation evidence for `s4-observation-builder` and
`s4-slice-builder`. It adds product-builder bindings adjacent to `s4-execution`
but does not claim completion of its worker/job-lifecycle responsibility. IMAP
was inspected read-only and its state was not changed. No HTTP, composition,
renderer or UI surface was added.

What was implemented:
- Observation markers and profiles are built from S3 records without reopening
  or decoding observation datasets. Exact identity, values, masks, units,
  timestamps, QC values and S3-declared QC vocabularies remain in the existing
  observation envelopes and wire format.
- S3 record positions provide deterministic S4 trace indices. CRS, vertical
  direction and provenance remain explicit per-version configuration because
  the S3 observation records do not carry them; unavailable source dtypes are
  represented as null rather than inferred.
- Depth slices preserve exact grid cells by default. Linear interpolation runs
  only when requested, never extrapolates, and records both source levels,
  source indices, weights, source dtype and delivered dtype.
- The slice wire format uses the shared little-endian, eight-byte-aligned
  layout and declares grid shape, C-order traversal, masks and source indices.

Tests and results:
Focused observation, managed-field, slice and wire tests passed. The active
suite `pytest ingestion/tests processing/tests serving/tests` completed with
275 passed and 10 live-environment skips. Compile, whitespace, IMAP and Graft
checks are recorded with the merge result.

Deviations or limitations:
- Repository-root pytest discovery also collects
  `archive/local-sources/test_end_to_end_local.py`; that archived reinstatement
  test cannot import the deliberately removed `ingestion.local_paths` module.
  The isolated failure was reproduced and not changed because archive code is
  outside this packet.
- Only exact and linear depth policies are supported. Linear interpolation
  requires two bracketing levels and masks output cells when either source cell
  is missing; there is no nearest-neighbour selection or extrapolation.
- Observation execution builders are typed callables. No new observation job
  lifecycle or transport endpoint is introduced in this packet.
