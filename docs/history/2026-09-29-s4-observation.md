# S4 observation markers and profiles

Feature:
Pure S4 builders turn a decoded row-oriented observation dataset into an
auditable marker product or one exact depth/pressure-versus-variable profile.
An S5 wire adapter describes the products and packs their arrays without
changing source values.

Requirements and IMAP refs:
This is implementation evidence for IMAP `s4-observation-builder`. It does not
claim complete observation UI, storage, HTTP, renderer, or SRS coverage. Shared
wire-layout behavior remains part of the existing S5 product-delivery path.

What was implemented:
- Exact platform and cycle/profile identity grouping for Argo- and
  glider-shaped row datasets, including integral-float identity normalization.
- Marker coordinates, source-row membership, vertical ranges, and explicit
  reports for profiles skipped because position/time or vertical data is
  unavailable.
- Exact profile source indices, vertical values, timestamps, requested
  measurements, units, missing-value masks, QC flags, and source-declared QC
  vocabularies.
- One shared little-endian, eight-byte-aligned wire-layout implementation used
  by both scalar point-field and observation products.

Tests and results:
`pytest processing/tests/test_observation.py serving/tests/test_wire_observation.py`
-- 24 passed. `pytest processing/tests serving/tests` -- 106 passed.

Deviations or limitations:
- Inputs must already be decoded in-memory `xarray.Dataset` objects with an
  explicit semantic descriptor; this feature does not read storage or paths.
- Observations are selected exactly. There is no interpolation, aggregation,
  unit conversion, coordinate averaging, or QC interpretation/filtering.
- QC `flag_values`, `flag_meanings`, and `conventions` are preserved only when
  the source declares them; absent attributes remain explicit null values.
- Marker building can skip unusable profiles but fails when none can produce a
  marker. Profile building remains an exact-identity operation.
