// The colourbar: palette, range, scale and units of what is on screen.

import { Group, Paper, Text } from "@mantine/core";

import { cssGradient } from "../renderer/colour";
import type { Display } from "../state/store";

export function Colourbar({ display, units, variable }: { display: Display; units: string; variable: string }) {
  const { minimum, maximum } = display.range;
  const middle = display.scale === "log" ? Math.sqrt(minimum * maximum) : (minimum + maximum) / 2;
  const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toPrecision(3));
  return (
    <Paper p="sm" w={320} withBorder shadow="md" aria-label={`Colour scale for ${variable}`}>
      <Text size="xs" c="dimmed" mb={6}>{variable} ({units}) · {display.scale}</Text>
      <div className="colour-bar" style={{ background: cssGradient(display.palette) }} />
      <Group justify="space-between" mt={4} className="mono">
        <Text size="xs">{fmt(minimum)}</Text><Text size="xs">{fmt(middle)}</Text><Text size="xs">{fmt(maximum)}</Text>
      </Group>
    </Paper>
  );
}
