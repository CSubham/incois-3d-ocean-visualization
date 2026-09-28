// What is shown versus what exists (IMAP s7-point-field-sampling-state).
// The view is sampled source cells, never a complete-resolution volume.

import { Alert, Paper, Stack, Table, Text, Title } from "@mantine/core";

import type { Budget } from "../api/client";
import type { ProductDescriptor } from "../api/wire";
import { formatUtc } from "./format";

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
  const rows: [string, string][] = [
    ["Time", formatUtc(p.identity.time_value)],
    ["Dataset", `${p.identity.dataset_id} · ${p.identity.dataset_version_id}`],
    ["Depth", `positive ${p.spatial_reference.vertical_positive} (${p.coordinates.units.depth}), drawn ×${verticalExaggeration}`],
    ["Reference", `${p.spatial_reference.crs}, not reprojected`],
  ];
  return (
    <Paper p="sm" withBorder shadow="md" aria-label="Sampling disclosure">
      <Stack gap={6}>
        <Title order={2} size="h6">{s.is_lossy ? "Sampled view" : "Every selected cell"}</Title>
        <Text size="xs">
          {n(s.delivered_point_count)} of {n(s.original_point_count)} source cells delivered
          ({share < 1 ? share.toFixed(2) : share.toFixed(0)}%), chosen evenly by grid index with no interpolation.
          {shown && <> {n(shown.points)} have values and are drawn; {n(shown.hiddenMissing)} are land or missing and are not drawn.</>}
        </Text>
        {budget?.reduced_by_server && (
          <Alert color="yellow" p={6}><Text size="xs">The server lowered the point budget from {n(budget.requested_points ?? 0)} to {n(budget.effective_points)}.</Text></Alert>
        )}
        {retry && (
          <Alert color="yellow" p={6}><Text size="xs">Re-requested at {n(retry.to)} points because {n(retry.from)} exceeded this view's limit.</Text></Alert>
        )}
        <Table withRowBorders={false} verticalSpacing={1}>
          <Table.Tbody>
            {rows.map(([k, v]) => (
              <Table.Tr key={k}><Table.Td w={80}><Text size="xs" c="dimmed">{k}</Text></Table.Td><Table.Td><Text size="xs">{v}</Text></Table.Td></Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Paper>
  );
}
