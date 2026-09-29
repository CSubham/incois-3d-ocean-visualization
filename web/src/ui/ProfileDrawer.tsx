// The selected float's profile beside the globe (IMAP s7-profile-chart):
// exact identity, time and position, and a Plotly depth- or pressure-versus-
// value chart. Plotly is loaded only when the first profile opens.

import { Alert, Drawer, Group, Loader, Stack, Text } from "@mantine/core";
import { useEffect, useMemo, useRef } from "react";

import type { ProfileState } from "../state/store";
import { formatUtc } from "./format";
import { profileFigure } from "./profileFigure";

function ProfileChart({ figure }: { figure: ReturnType<typeof profileFigure> }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let cancelled = false;
    const target = element.current;
    void import("plotly.js-basic-dist-min").then((Plotly) => {
      if (cancelled || !target) return;
      void Plotly.react(target, figure.data as Plotly.Data[], figure.layout as Partial<Plotly.Layout>,
        { displaylogo: false, responsive: true });
    });
    return () => {
      cancelled = true;
      if (target) void import("plotly.js-basic-dist-min").then((Plotly) => Plotly.purge(target));
    };
  }, [figure]);
  return <div ref={element} style={{ width: "100%", height: 460 }} aria-label="Profile chart" />;
}

export function ProfileDrawer({ profile, onClose }: { profile: ProfileState; onClose: () => void }) {
  const pick = profile.pick;
  // One figure per profile, so Plotly redraws only when the profile changes.
  const figure = useMemo(() => (profile.profile ? profileFigure(profile.profile) : null), [profile.profile]);
  return (
    <Drawer opened={profile.phase !== "closed"} onClose={onClose} position="right" size={480}
      title={pick ? `Float ${pick.platformId} · cycle ${pick.cycle}` : "Profile"} withOverlay={false}
      lockScroll={false} trapFocus={false}>
      {pick && (
        <Text size="xs" c="dimmed" mb="sm" className="mono">
          {formatUtc(pick.observedAt)} · {pick.latitude.toFixed(3)}°N {pick.longitude.toFixed(3)}°E
        </Text>
      )}
      {profile.phase === "loading" && <Group gap="sm"><Loader size="xs" /><Text size="sm">Loading the profile…</Text></Group>}
      {profile.phase === "failed" && (
        <Alert color="red" title="The profile could not be shown" role="alert">{profile.failure?.message}</Alert>
      )}
      {profile.phase === "shown" && profile.profile && figure && (
        <Stack gap="xs">
          <ProfileChart figure={figure} />
          {profile.profile.variables.map((variable) => (
            <Text key={variable.name} size="xs" c="dimmed">
              {variable.name} QC:{" "}
              {variable.qcMeanings
                ? [...variable.qcMeanings].map(([flag, meaning]) => `${flag} = ${meaning}`).join(", ")
                : variable.qcFlags ? "flags shown as recorded; the source does not declare their meanings" : "no QC variable"}
            </Text>
          ))}
        </Stack>
      )}
    </Drawer>
  );
}
