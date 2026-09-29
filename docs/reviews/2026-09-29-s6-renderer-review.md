# S6 renderer deviation review

Reviewed `feature/c3-m1-browser-c@d143a19` after H2 merged to `main` at
`507e1cf`. Scope was read-only:
`web/src/renderer/**`, `web/src/api/wire.ts`,
`web/src/api/observationWire.ts`, and `web/src/state/store.ts`.

The locked SRS and HLSA decide requirements and ownership. The working LLD
§7 and D6 plus the technical investigation §C S6 and §F.4 identify design and
research departures. Proposed D12 authorizes CesiumJS, geodetic placement and
reversible exaggerated ellipsoid depth in place of D6's conditional Three.js
implementation; choosing Cesium is therefore not itself a finding.

## Result

Not ready to merge as a clean S6 boundary. The point-field path is honestly
labelled as a sampled prototype and most of the renderer facade is well
isolated, but the observation decoder rejects a valid S5 representation.
Five medium-severity issues can also produce an unvalidated marker frame,
stale scientific context, false recovery state, undisclosed precision loss or
unit-dependent exaggeration error.

Finding counts: **1 high, 5 medium, 1 low**.

## High-severity findings

### H1 — the marker decoder rejects valid source-dtype-preserving S5 products

**Tag: DEPARTS-LLD-OR-RESEARCH**

`web/src/api/observationWire.ts:45-50` requires longitude, latitude and
vertical-range arrays to be `Float64Array`. The S5 wire contract does not make
that promise: `serving/wire_observation.py:71-87` preserves each marker
array's source dtype through the shared layout. A valid marker product built
from the repository's Argo fixture is emitted as `<f4` for all four arrays and
is rejected by this decoder before S6 can draw it.

The committed browser fixture happens to use the managed-record path, whose
Python floats become `<f8`, so the current test conceals the contract mismatch.
This violates the LLD's replaceable S5/S6 product contract and the
investigation's requirement that a renderer consume the declared artifact
encoding rather than a narrower incidental representation.

Required correction: accept the same declared numeric dtypes as the shared S5
wire layout and retain the actual typed-array type in `MarkerSet`, or version
the producer contract if S5 deliberately converts marker geometry to one
declared dtype. Add a fixture for a source-preserved float32 marker product.

## Medium-severity findings

### M1 — marker CRS is discarded before Cesium assumes longitude/latitude degrees

**Tag: CONTRADICTS-LOCKED**

`web/src/api/observationWire.ts:14-28` receives the marker product's
`spatial_reference`, but `MarkerSet` at `web/src/api/observationWire.ts:31-43`
does not carry it and `decodeMarkers` at lines 84-95 drops it. The adapter then
passes every marker directly to `Cartesian3.fromDegrees` at
`web/src/renderer/cesium/CesiumRenderer.ts:186-201` without the refusal used by
the model layer. Any otherwise valid marker product in a non-WGS84 or
unrecognised frame is silently plotted as degrees.

Current configured observation sources are WGS84, so the present demo is
placed correctly, but the S6 contract is not safe for another admitted product
and cannot establish IDO-001's geospatial accuracy. Carry the CRS through the
renderer-independent marker set, validate it through the shared transform
gate, and emit `unsupported` for an unhandled frame.

### M2 — an unsupported new product leaves old geometry under new metadata

**Tag: DEPARTS-LLD-OR-RESEARCH**

The reducer commits the newly succeeded descriptor at
`web/src/state/store.ts:138-156`. `showPointField` then validates CRS and depth
units before calling `clear()` at
`web/src/renderer/cesium/CesiumRenderer.ts:114-128`. On refusal it emits an
unsupported event but leaves the previous layer visible. S7 now holds the new
variable, units, range and sampling descriptor while Cesium still displays the
old field.

An alert is preferable to a blank canvas, but it does not make mismatched
scientific metadata and geometry safe. Make display replacement transactional:
either clear/retire the old layer when the new product is refused and keep the
new descriptor out of the shown state, or retain the old descriptor explicitly
as the still-displayed product.

### M3 — context loss and recovery are not represented truthfully

**Tag: DEPARTS-LLD-OR-RESEARCH**

`web/src/renderer/cesium/CesiumRenderer.ts:87-93` turns context loss into the
same generic error as a render failure, provides no restored/reinitializing
event and tells the user to reload. More seriously,
`web/src/state/store.ts:176-186` changes any renderer error back to `ok` on an
ordinary display edit even though no context was restored. Conversely a later
`ready` event at lines 160-167 does not clear an earlier unsupported/error
state.

This departs from LLD §7 and research §C S6, which require explicit capability,
lost-context and recovery behavior rather than a frozen or falsely healthy
canvas. Give context loss/restoration explicit facade events and make `ok`
reachable only after a real mount/restoration or successful ready transition.

### M4 — rendering and hover silently narrow scalar values to float32

**Tag: DEPARTS-LLD-OR-RESEARCH**

The point decoder correctly accepts the S5 numeric dtype, but
`web/src/renderer/cesium/CesiumRenderer.ts:129-143` copies every valid value
into a `Float32Array`. Colour normalization and the physical hover sample at
lines 329-336 then use that narrowed value. A float64 or sufficiently large
integer product therefore loses precision after a lossless S5 delivery, with
no encoding or error bound disclosed.

Keep the decoded numeric array (or JavaScript numbers) for colour and reported
values. If a future GPU path needs float32, treat that as an explicit display
encoding while preserving the original value for interaction and disclosure.

### M5 — suggested depth exaggeration assumes metres although S6 accepts kilometres

**Tag: DEPARTS-LLD-OR-RESEARCH**

`web/src/state/store.ts:94-99` always divides the selected vertical span by
1000. The renderer's transform at `web/src/renderer/transform.ts:13-47`
explicitly accepts both metre and kilometre units. A kilometre-valued product
is therefore positioned correctly by Cesium but receives a suggestion roughly
1000 times too large from S7.

Derive the suggestion from the successful product's declared depth units, or
restrict the accepted renderer contract to metres and refuse everything else.
The display transform remains reversible; the defect is the unitless suggested
factor layered on top of it.

## Low-severity quality findings

### L1 — the Cesium adapter's critical behavior has no adapter-level tests

**Tag: QUALITY**

`web/src/renderer/cesium/CesiumRenderer.ts:64-343` owns capability refusal,
mask filtering/counting, resource fallback, layer disposal, actual Cesium pick
shape and context-loss events. Tests cover pure colour, transform and
`markerPick` helpers, but none instantiates the adapter or a scene test double.
The decoder fixture therefore cannot catch the stale-layer and state-transition
issues above, and exact identity is proven only after an index has already been
resolved.

Add a narrow Cesium-boundary test double covering masked-cell count, resource
and unsupported events, replacement/cleanup, context loss/restoration and an
actual pick object. A full browser screenshot suite is not required for these
contract tests.

## Requirement and boundary outcome

- Proposed D12 is isolated correctly: S7 state and the renderer facade expose
  no Cesium object. The concrete engine is selected at composition.
- Model CRS and depth units are refused when unsupported, physical point
  positions are recomputed from retained coordinates, and vertical
  exaggeration is reversible display state. M1 and M5 are the marker and
  suggestion exceptions.
- Masked or non-finite model cells are not drawn. The `ready` event reports the
  shown count and the number hidden, satisfying the scoped mask behavior.
- Marker identities remain index-aligned through text decoding and
  `markerPick`; the S6 pick event carries dataset version, platform and cycle,
  never an engine object.
- IDO-002 is only partially evidenced. S6 emits the exact pick, while
  `web/src/state/store.ts:173-174` deliberately ignores marker events until the
  later observation workflow; the current branch does not yet make selection
  user-observable.
- The sampled scalar point field is partial MVR-001 evidence and can display
  temperature or salinity scalars. It is not full-water-column volume evidence
  and supplies no current-vector layer, so it does not close MVR-006. The UI's
  prototype label and IMAP status are honest about that limitation.
- The point-field decoder supports the same browser-viewable dtype family as
  S5 and checks format, total byte length, named arrays, counts and mask dtype.
  H1 is the observation-decoder exception.

## Evidence run

- `npm test -- --run`: **29 passed in 8 files**.
- `npm run typecheck`: **passed**.
- `npm run build`: **passed**; Vite transformed 2297 modules and produced the
  Cesium application bundle and same-origin static assets.
- A read-only Python probe through `serving.wire_observation.describe` produced
  `<f4` longitude, latitude, vertical-minimum and vertical-maximum arrays from
  the repository's valid Argo marker fixture, reproducing H1's rejected case.
- Graft was used for source orientation and caller tracing. IMAP was inspected
  read-only from the shared schema-5 map for S6, the renderer facade, scene,
  fallback, marker and cross-cutting responsibilities. The feature worktree's
  schema-1 copy was not migrated because this packet explicitly forbids IMAP
  writes.

No implementation or test file on `feature/c3-m1-browser-c` was changed.
