// The selected float's profile beside the globe (IMAP s7-profile-chart):
// who and where in one line, a switch between variables, and the chart.
// Quality-control details stay one hover away. Plotly is loaded only when
// the first profile opens.

import { Alert, Badge, Drawer, Group, SegmentedControl, Skeleton, Stack, Text, Tooltip } from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";

import type { ProfileState } from "../state/store";
import { formatUtc } from "./format";
import { profileFigure, variableLabel } from "./profileFigure";
import { formatPosition } from "./surfaceFormat";

function ProfileChart({ figure }: { figure: ReturnType<typeof profileFigure> }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    const target = element.current;
    void import("plotly.js-basic-dist-min").then((Plotly) => {
      if (cancelled || !target) return;
      void Plotly.react(target, figure.data as Plotly.Data[], figure.layout as Partial<Plotly.Layout>,
        { displaylogo: false, responsive: true, displayModeBar: false });
    });
    return () => {
      cancelled = true;
      if (target) void import("plotly.js-basic-dist-min").then((Plotly) => Plotly.purge(target));
    };
  }, [figure]);
  return <div ref={element} style={{ width: "100%", height: "min(62vh, 520px)" }} aria-label="Profile chart" />;
}

export function ProfileDrawer({ profile, onClose }: { profile: ProfileState; onClose: () => void }) {
  const pick = profile.pick;
  const variables = profile.profile?.variables ?? [];
  const [choice, setChoice] = useState("all");
  const shown = useMemo(() => (choice === "all" ? undefined : [choice]), [choice]);
  // One figure per profile and choice, so Plotly redraws only when either changes.
  const figure = useMemo(
    () => (profile.profile ? profileFigure(profile.profile, shown) : null), [profile.profile, shown]);
  const qc = variables
    .map((v) => v.qcMeanings
      ? `${variableLabel(v)}: ${[...v.qcMeanings].map(([flag, meaning]) => `${flag} ${meaning}`).join(", ")}`
      : v.qcFlags ? `${variableLabel(v)}: flags as recorded (meanings not declared)` : null)
    .filter((line): line is string => line !== null);

  return (
    <Drawer
      opened={profile.phase !== "closed"} onClose={onClose} position="right" size={420}
      withOverlay={false} lockScroll={false} trapFocus={false}
      classNames={{ content: "glass", header: "drawer-header" }}
      title={pick && (
        <div>
          <Text fw={700}>Argo float {pick.platformId}</Text>
          <Text size="xs" c="dimmed" className="mono">
            Cycle {pick.cycle} · {formatUtc(pick.observedAt)} · {formatPosition(pick.longitude, pick.latitude)}
          </Text>
        </div>
      )}
    >
      {profile.phase === "loading" && <Skeleton height={360} radius="sm" />}
      {profile.phase === "failed" && (
        <Alert color="red" variant="light" title="Profile unavailable">{profile.failure?.message}</Alert>
      )}
      {profile.phase === "shown" && figure && (
        <Stack gap="sm">
          <Group justify="space-between" wrap="nowrap">
            {variables.length > 1 ? (
              <SegmentedControl
                size="xs" value={choice} onChange={setChoice}
                data={[...variables.map((v) => ({ value: v.name, label: variableLabel(v) })), { value: "all", label: "Both" }]}
              />
            ) : <span />}
            {qc.length > 0 && (
              <Tooltip multiline w={300} label={qc.join(" · ")} position="bottom-end">
                <Badge variant="outline" color="gray" size="sm" style={{ cursor: "help" }}>QC</Badge>
              </Tooltip>
            )}
          </Group>
          <ProfileChart figure={figure} />
        </Stack>
      )}
    </Drawer>
  );
}
