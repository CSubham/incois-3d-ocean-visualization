// Palette, range, scale, opacity and vertical exaggeration as persistent
// renderer state (IMAP s7-display-controls). No change here reprocesses data.

import { Anchor, Button, Fieldset, Group, NumberInput, SegmentedControl, Select, Slider, Stack, Text, Title, Tooltip } from "@mantine/core";

import type { Range } from "../api/wire";
import { cssGradient, logScaleProblem, PALETTES } from "../renderer/colour";
import type { PaletteName, ScaleKind } from "../renderer/contract";
import type { Display } from "../state/store";

interface Props {
  display: Display;
  fullSubsetRange: Range | null;
  enabled: boolean;
  onChange: (patch: Partial<Omit<Display, "rangeSource" | "exaggerationSource">>) => void;
  onUseFullSubsetRange: () => void;
  onResetCamera: () => void;
}

const EXAGGERATION = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];

export function DisplayPanel({ display, fullSubsetRange, enabled, onChange, onUseFullSubsetRange, onResetCamera }: Props) {
  const logProblem = logScaleProblem(display.range.minimum, display.range.maximum);
  const stepIndex = EXAGGERATION.reduce((best, v, i) =>
    Math.abs(v - display.verticalExaggeration) < Math.abs(EXAGGERATION[best] - display.verticalExaggeration) ? i : best, 0);
  const setRange = (key: "minimum" | "maximum") => (value: string | number) => {
    if (typeof value === "number" && Number.isFinite(value)) onChange({ range: { ...display.range, [key]: value } });
  };
  return (
    <Stack gap="sm" component="section" aria-label="Display">
      <Title order={2} size="h6" tt="uppercase" c="dimmed">Display</Title>
      <Fieldset variant="unstyled" disabled={!enabled}>
        <Stack gap="sm">
          <Select label="Palette" value={display.palette} allowDeselect={false}
            data={PALETTES.map((p) => ({ value: p, label: p }))}
            onChange={(v) => v && onChange({ palette: v as PaletteName })}
            leftSection={<div className="colour-bar" style={{ width: 16, background: cssGradient(display.palette) }} />} />
          <Group grow gap="xs">
            <NumberInput label="Range min" value={display.range.minimum} decimalScale={3} onChange={setRange("minimum")} />
            <NumberInput label="Range max" value={display.range.maximum} decimalScale={3} onChange={setRange("maximum")} />
          </Group>
          <Text size="xs" c="dimmed">
            {display.rangeSource === "full-subset" ? "Range of the full selected subset, before sampling." : "Custom range."}{" "}
            {display.rangeSource === "custom" && fullSubsetRange?.minimum != null && (
              <Anchor component="button" size="xs" onClick={onUseFullSubsetRange}>Use full-subset range</Anchor>
            )}
          </Text>
          <Tooltip label={logProblem ?? ""} disabled={!logProblem} position="right">
            <SegmentedControl fullWidth value={display.scale} aria-label="Colour scale"
              onChange={(v) => onChange({ scale: v as ScaleKind })}
              data={[{ value: "linear", label: "Linear" }, { value: "log", label: "Logarithmic", disabled: logProblem !== null }]} />
          </Tooltip>
          <div>
            <Text size="sm" fw={500}>Opacity <Text span c="dimmed" size="sm">{Math.round(display.opacity * 100)}%</Text></Text>
            <Slider aria-label="Opacity" min={0.05} max={1} step={0.05} value={display.opacity}
              onChange={(opacity) => onChange({ opacity })} label={(v) => `${Math.round(v * 100)}%`} />
          </div>
          <div>
            <Text size="sm" fw={500}>Vertical exaggeration <Text span c="dimmed" size="sm">×{display.verticalExaggeration}</Text></Text>
            <Slider aria-label="Vertical exaggeration" min={0} max={EXAGGERATION.length - 1} step={1} value={stepIndex}
              label={(i) => `×${EXAGGERATION[i]}`} onChange={(i) => onChange({ verticalExaggeration: EXAGGERATION[i] })} />
          </div>
          <Button variant="light" onClick={onResetCamera}>Fly to region</Button>
        </Stack>
      </Fieldset>
    </Stack>
  );
}
