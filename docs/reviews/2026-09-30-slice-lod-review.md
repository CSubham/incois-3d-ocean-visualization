# S4/S5 slice LOD non-author review

Reviewed as a non-author on `feature/c7-surface-layers-c` at `40e4144`, with
the vector-slice introduction in `5ffca66` inspected separately. Authority was
the locked SRS and HLSA; the working LLD was not used to authorize behavior.

## High

1. **A latitude/longitude block mean was not area-conservative — fixed here.**
   `processing/slice_reduction.py:44-59` in `40e4144` divided the unweighted
   sum of valid cells by their count. Equal-sized angular cells have areas
   proportional to `cos(latitude)`, so unequal-latitude cells contributed as
   if they covered the same area. This branch applies a zero weight to missing
   cells and a cosine-latitude weight to valid cells, keeps an all-missing
   block missing, refuses non-regular/non-degree grids, and records CF
   `cell_methods = "area: mean"` plus the weighting basis.

2. **The global vector route has no display LOD and can still return the full
   source grid — remains open.** `serving/slices.py:80-87` sends vector
   requests only the source-work ceiling, while `serving/compose.py:44-48` and
   `serving/compose.py:110-116` raise that ceiling to 25M cells so a 19M-cell
   global level is accepted. `processing/vector_slice.py:64-69` additionally
   derives a float64 speed grid, and `serving/wire_vector.py:20-44` serializes
   both components, speed and mask. The scalar 2M display budget does not
   protect this path. A vector-specific S4 reduction or the separately reviewed
   bounded-glyph product must sit before the S5 wire adapter; S5 should not
   invent that scientific reduction.

## Medium

1. **The original reducer missed the stated global-scale performance target —
   fixed here.** `processing/slice_reduction.py:46-58` in `40e4144` allocated
   padded source-sized boolean and float64 grids and also materialized the
   float64 conversion used by `np.where`. On this machine, the 4251x4500,
   factor-4 kernel took 504.473 ms and the process peaked at 493,484 KiB.
   This branch traverses bounded contiguous block-row groups and retains only
   output-sized accumulators plus a bounded working chunk. The public benchmark
   reports a 260.620 ms median and a 268,120 KiB process peak for five measured
   reductions at 35% masked land.

2. **Vector alignment is weaker than the product claim — remains open.**
   `processing/vector_slice.py:46-62` checks coordinate values, time index,
   depth indices and units, but not dataset/version identity, actual time
   value, spatial reference, interpolation weights, coordinate roles, or
   horizontal source-index sequences. Two independently constructed slices
   can therefore pass while not identifying the same managed cells. The
   normal managed builder currently requests both from one version, which
   limits exposure but does not make the public S4 builder safe.

3. **A non-positive direct side limit could loop forever — fixed here.**
   `processing/slice_reduction.py:38-40` in `40e4144` incremented the factor
   until the delivered side was at most `maximum_side`; for zero that condition
   is impossible. S5 configuration validated its own value, but the pure S4
   function did not. The reducer now validates budget, source shape and side
   limit before the loop.

4. **The vector wire omits horizontal source indices — remains open.**
   `serving/wire_vector.py:20-44` carries time and depth source indices but not
   the latitude/longitude source-index arrays present on each component. This
   weakens cell-level auditability even though the component metadata otherwise
   remains available on the control path.

## Low

1. **The delivered-mean dtype comment contradicted the code — fixed here.**
   `processing/slice_reduction.py:80-81` in `40e4144` said means were float64,
   but `result_type(float32, float32)` delivered float32. The optimized path
   now intentionally accumulates and delivers at least float32, preserves
   float64 sources, records the actual `delivered_dtype`, and has an explicit
   float32 test.

2. **The final edge block's source range was only implicit — fixed here.**
   `processing/depth_slice.py:130-145` described each delivered index as the
   first source cell and carried the factor/source shape, which was sufficient
   to infer but not directly understand the shortened edge range. The wording
   now states that each range is clipped at the source-axis end, and separately
   states that delivered coordinates are arithmetic centres of source cell
   centres.

## Confirmed correct

- Missing cells do not influence a block and an all-missing block stays
  missing. The new weighting preserves both properties.
- Edge blocks use only cells actually present. Their longitude and latitude
  coordinates are the arithmetic centres of those source coordinate centres.
- `physical_range` is recomputed from delivered values and the delivered mask;
  it does not claim the unreduced source extrema.
- The source-work ceiling is checked from coordinate counts before values are
  read (`processing/subsetter.py:182-199`). Display budget and source-work
  ceiling are separate concepts.
- Stage ownership is clean: S5 selects/caps a view budget, S4 performs and
  declares the aggregation, and neither the reducer nor its product imports a
  transport, database, object-store or renderer implementation.
- Linear depth interpolation metadata remains separate from horizontal
  coarsening. The latter is explicitly an area aggregation, not interpolation.

## Reproduction

```bash
python -m processing.benchmark.slice_reduction \
  --shape 4251 4500 --budget 2000000 --land-fraction 0.35 --repeats 5
```

The benchmark constructs a float32 depth-slice product before timing, performs
one warm-up, times the public `reduce_depth_slice` function, reports every
sample and exits non-zero when its median misses the requested target.
