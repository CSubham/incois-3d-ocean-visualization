// Loading, failure and unsupported states (IMAP s7-visible-failures):
// never a blank or silently stale view.

import { Alert, Group, Loader, Paper, Text } from "@mantine/core";

import type { State } from "../state/store";

interface Props {
  catalogue: State["catalogue"];
  request: State["request"];
  renderer: State["renderer"];
  displayProblem: string | null;
  hasProduct: boolean;
}

export function StatusBanner({ catalogue, request, renderer, displayProblem, hasProduct }: Props) {
  if (renderer.phase === "unsupported") return <Alert color="red" title="3D view unavailable" role="alert">{renderer.reason}</Alert>;
  if (renderer.phase === "lost") return <Alert color="red" title="3D view stopped" role="alert">{renderer.reason}</Alert>;
  if (renderer.phase === "failed") return <Alert color="red" title="Display problem" role="alert">{renderer.reason}</Alert>;
  if (displayProblem) return <Alert color="yellow" title="Display setting not applied" role="alert">{displayProblem}</Alert>;
  if (request.phase === "loading") {
    return (
      <Paper px="md" py={8} withBorder shadow="md" role="status">
        <Group gap="sm"><Loader size="xs" /><Text size="sm">{request.retryFrom ? "Preparing a lower-density field…" : "Preparing the field…"}</Text></Group>
      </Paper>
    );
  }
  if (request.phase === "failed") {
    return (
      <Alert color="red" title="The field could not be shown" role="alert">
        {request.failure.message}{hasProduct ? " The previous field is still shown." : ""}
      </Alert>
    );
  }
  if (catalogue.phase === "failed") return <Alert color="red" title="Catalogue unavailable" role="alert">{catalogue.message}</Alert>;
  if (!hasProduct && catalogue.phase === "ready") {
    return <Paper px="md" py={8} withBorder shadow="md" role="status"><Text size="sm">Choose a selection and press Show field.</Text></Paper>;
  }
  return null;
}
