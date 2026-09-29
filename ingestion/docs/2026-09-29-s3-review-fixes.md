# S3 review fixes: marker provenance, vertical semantics and source encoding

This note records the S3 corrections made after the pre-S7 S3–S5 review. It
describes implemented contracts, not new requirements.

## Profile marker policy

For each exact platform/cycle group, S3 persists the first source row whose
longitude and latitude are finite and in range and whose time is valid. The
longitude, latitude and time always come from that same row; none is averaged
or independently reduced. `observation_profile.representative_source_index`
records its zero-based position in the immutable managed object. Legacy rows
may have a null source index.

## Semantic vertical extents

Both dataset versions and observation-profile index rows now store
`vertical_min`, `vertical_max`, `vertical_kind` and `vertical_units`.
`vertical_kind` is `depth` or `pressure` when units establish that meaning.
The existing `depth_min` and `depth_max` fields remain a depth-only
compatibility view and are null for pressure coordinates. Applying
`storage/migrations/0001_catalogue_baseline.sql` (formerly `storage/schema.sql`) repeatedly is safe; it migrates legacy extents from their
preserved vertical units without converting pressure to depth.

## S3 read-contract handoff

The optional fields below are populated by current catalogue and in-memory
queries and remain `None` on caller-created legacy records that lack them:

- `ProfileMarker.representative_source_index`
- `ObservationProfile.source_indices`
- `ObservationProfile.depth_source_dtype`
- `ObservationProfile.time_source_dtype`
- `ObservationProfile.time_encoding` (`units` and `calendar`)
- `ProfileVariable.source_dtype`
- `ProfileVariable.qc_source_dtype`

`DatasetExtent.vertical_min`, `vertical_max`, `vertical_kind` and
`vertical_units` are the semantic catalogue extent fields for downstream S4
and S5 consumers. `DatasetExtent.depth_min` and `depth_max` must only be used
for physical depth.
