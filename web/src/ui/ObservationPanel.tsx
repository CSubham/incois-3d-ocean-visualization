// Observation dataset, time window and "Show floats" (IMAP s7-selection-controls,
// observation half). Markers are searched inside the model field's region.

import { Button, Select, Stack, Text, TextInput, Title } from "@mantine/core";

import type { Observations } from "../state/store";
import { formatUtc } from "./format";

interface Props {
  observations: Observations;
  canSearch: boolean;
  onSelectVersion: (versionId: string) => void;
  onEditWindow: (patch: { timeStart?: string; timeEnd?: string }) => void;
  onShow: () => void;
}

export function ObservationPanel({ observations, canSearch, onSelectVersion, onEditWindow, onShow }: Props) {
  const { versions } = observations;
  return (
    <Stack gap="sm" component="section" aria-label="Observations">
      <Title order={2} size="h6" tt="uppercase" c="dimmed">Observations</Title>
      {versions === null ? (
        <Text size="sm" c="red">The observation catalogue could not be read.</Text>
      ) : versions.length === 0 ? (
        <Text size="sm" c="dimmed">No observation datasets are stored yet.</Text>
      ) : (
        <>
          <Select label="Instrument dataset" value={observations.versionId} allowDeselect={false}
            data={versions.map((v) => ({
              value: v.dataset_version_id,
              label: `${v.dataset_id} · ${v.vertical_kind} (${v.vertical_units})`,
            }))}
            onChange={(v) => v && onSelectVersion(v)} />
          <TextInput label="From (UTC, ISO 8601)" value={observations.timeStart}
            onChange={(e) => onEditWindow({ timeStart: e.currentTarget.value })} />
          <TextInput label="To (UTC, ISO 8601)" value={observations.timeEnd}
            onChange={(e) => onEditWindow({ timeEnd: e.currentTarget.value })} />
          <Button variant="light" onClick={onShow} disabled={!canSearch}
            loading={observations.phase === "loading"}>Show floats in this region</Button>
          <Text size="xs" c={observations.phase === "failed" ? "red" : "dimmed"} role="status">
            {observations.phase === "shown" && (observations.count === 0
              ? `No profiles between ${formatUtc(observations.timeStart)} and ${formatUtc(observations.timeEnd)} in this region.`
              : `${observations.count} profiles shown. Select one on the globe for its profile.`)}
            {observations.phase === "failed" && observations.failure?.message}
          </Text>
        </>
      )}
    </Stack>
  );
}
