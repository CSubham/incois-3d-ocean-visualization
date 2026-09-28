// Dataset, variable, time, region, depth and density selection
// (IMAP s7-selection-controls). A request is made only on "Show field".

import { Button, NumberInput, Select, SimpleGrid, Stack, Text, Title } from "@mantine/core";

import type { CatalogueVersion } from "../api/client";
import type { Selection, State } from "../state/store";
import { formatUtc as utc } from "./format";

interface Props {
  catalogue: State["catalogue"];
  selection: Selection | null;
  loading: boolean;
  maximumPoints: number;
  onSelectVersion: (id: string) => void;
  onEdit: (patch: Partial<Omit<Selection, "versionId">>) => void;
  onShow: () => void;
}


function versionLabel(version: CatalogueVersion): string {
  const time = version.time_values?.[0] ?? version.extent.time_start;
  return `${version.dataset} · ${time ? utc(time) : "time unknown"}`;
}

const num = (value: string | number) => (typeof value === "number" && Number.isFinite(value) ? value : null);

export function SelectionPanel({ catalogue, selection, loading, maximumPoints, onSelectVersion, onEdit, onShow }: Props) {
  if (catalogue.phase !== "ready" || !selection) {
    return (
      <Stack gap="xs">
        <Title order={2} size="h6" tt="uppercase" c="dimmed">Data</Title>
        <Text size="sm" c="dimmed">
          {catalogue.phase === "loading" ? "Loading the catalogue…"
            : catalogue.phase === "failed" ? catalogue.message
            : "No model fields are stored yet."}
        </Text>
      </Stack>
    );
  }
  const version = catalogue.versions.find((v) => v.id === selection.versionId)!;
  const times = version.time_values ?? (version.extent.time_start ? [version.extent.time_start] : []);
  const field = (key: keyof Omit<Selection, "versionId" | "variable" | "time">) =>
    (value: string | number) => { const n = num(value); if (n !== null) onEdit({ [key]: n }); };
  return (
    <Stack gap="sm" component="section" aria-label="Data selection">
      <Title order={2} size="h6" tt="uppercase" c="dimmed">Data</Title>
      <Select label="Dataset version" value={selection.versionId} allowDeselect={false}
        data={catalogue.versions.map((v) => ({ value: v.id, label: versionLabel(v) }))}
        onChange={(v) => v && onSelectVersion(v)} />
      <Select label="Variable" value={selection.variable} allowDeselect={false}
        data={version.variables.map((v) => ({ value: v.name, label: v.units ? `${v.name} (${v.units})` : v.name }))}
        onChange={(v) => v && onEdit({ variable: v })} />
      <Select label="Time" value={selection.time} allowDeselect={false} searchable={times.length > 10}
        data={times.map((t) => ({ value: t, label: utc(t) }))}
        onChange={(v) => v && onEdit({ time: v })} />
      <SimpleGrid cols={2} spacing="xs">
        <NumberInput label="West (°E)" value={selection.west} onChange={field("west")} decimalScale={3} />
        <NumberInput label="East (°E)" value={selection.east} onChange={field("east")} decimalScale={3} />
        <NumberInput label="South (°N)" value={selection.south} onChange={field("south")} decimalScale={3} />
        <NumberInput label="North (°N)" value={selection.north} onChange={field("north")} decimalScale={3} />
        <NumberInput label="Depth from (m)" value={selection.depthMinimum} onChange={field("depthMinimum")} min={0} />
        <NumberInput label="Depth to (m)" value={selection.depthMaximum} onChange={field("depthMaximum")} min={0} />
      </SimpleGrid>
      <NumberInput label="Points to show" description={`Up to ${maximumPoints.toLocaleString()} for this view`}
        value={selection.maximumPoints} min={1} max={maximumPoints} step={10_000} thousandSeparator=","
        onChange={field("maximumPoints")} />
      <Button onClick={onShow} loading={loading} fullWidth>Show field</Button>
    </Stack>
  );
}
