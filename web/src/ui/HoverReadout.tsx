// The source cell under the pointer, in physical units.

import { Paper, Table, Text } from "@mantine/core";

import type { PointSample } from "../renderer/contract";

export function HoverReadout({ sample, units, variable }: { sample: PointSample; units: string; variable: string }) {
  const rows: [string, string][] = [
    [variable, `${sample.value.toFixed(3)} ${units}`],
    ["Latitude", `${sample.latitude.toFixed(3)}°`],
    ["Longitude", `${sample.longitude.toFixed(3)}°`],
    ["Depth", `${sample.depth.toFixed(1)} m`],
  ];
  return (
    <Paper p="xs" withBorder shadow="md" aria-live="polite" aria-label="Value under pointer">
      <Table withRowBorders={false} verticalSpacing={2} className="mono">
        <Table.Tbody>
          {rows.map(([k, v]) => (
            <Table.Tr key={k}><Table.Td><Text size="xs" c="dimmed">{k}</Text></Table.Td><Table.Td><Text size="xs" fw={500}>{v}</Text></Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}
