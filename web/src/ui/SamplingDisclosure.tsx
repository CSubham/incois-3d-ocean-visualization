// What is shown versus what exists (IMAP s7-point-field-sampling-state).
// The view is sampled source cells, never a complete-resolution volume.

import type { Budget } from "../api/client";
import type { ProductDescriptor } from "../api/wire";

interface Props {
  product: ProductDescriptor;
  budget: Budget | null;
  shown: { points: number; hiddenMissing: number } | null;
  retry: { from: number; to: number } | null;
  verticalExaggeration: number;
}

const n = (value: number) => value.toLocaleString();

export function SamplingDisclosure({ product, budget, shown, retry, verticalExaggeration }: Props) {
  const p = product.product;
  const s = p.sampling;
  const share = s.original_point_count ? (100 * s.delivered_point_count) / s.original_point_count : 100;
  return (
    <section className="disclosure" aria-label="Sampling disclosure">
      <h2>{s.is_lossy ? "Sampled view" : "Every selected cell"}</h2>
      <p>
        {n(s.delivered_point_count)} of {n(s.original_point_count)} source cells delivered
        ({share < 1 ? share.toFixed(2) : share.toFixed(0)}%), chosen evenly by grid index
        with no interpolation. {shown && <>{n(shown.points)} have values and are drawn;
        {" "}{n(shown.hiddenMissing)} are land or missing and are not drawn.</>}
      </p>
      {budget?.reduced_by_server && (
        <p className="warn">The server lowered the point budget from {n(budget.requested_points ?? 0)} to {n(budget.effective_points)}.</p>
      )}
      {retry && (
        <p className="warn">Re-requested at {n(retry.to)} points because {n(retry.from)} exceeded this view's limit.</p>
      )}
      <dl>
        <dt>Time</dt><dd>{p.identity.time_value.replace("T", " ").slice(0, 19)} UTC</dd>
        <dt>Dataset</dt><dd>{p.identity.dataset_id} · version {p.identity.dataset_version_id}</dd>
        <dt>Depth</dt><dd>positive {p.spatial_reference.vertical_positive}, {p.coordinates.units.depth}; drawn ×{verticalExaggeration}</dd>
        <dt>Reference</dt><dd>{p.spatial_reference.crs}, not reprojected</dd>
      </dl>
    </section>
  );
}
