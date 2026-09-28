// Loading, failure and unsupported states (IMAP s7-visible-failures):
// never a blank or silently stale view.

import type { State } from "../state/store";

interface Props {
  catalogue: State["catalogue"];
  request: State["request"];
  renderer: State["renderer"];
  hasProduct: boolean;
}

export function StatusBanner({ catalogue, request, renderer, hasProduct }: Props) {
  let tone: "info" | "error" = "info";
  let text: string | null = null;
  if (renderer.phase === "unsupported") { tone = "error"; text = `3D view unavailable: ${renderer.reason}`; }
  else if (renderer.phase === "error") { tone = "error"; text = `Display problem: ${renderer.reason}`; }
  else if (request.phase === "loading") text = request.retryFrom ? "Preparing a lower-density field…" : "Preparing the field…";
  else if (request.phase === "failed") {
    tone = "error";
    text = `${request.failure.message}${hasProduct ? " — the previous field is still shown." : ""}`;
  }
  else if (catalogue.phase === "failed") { tone = "error"; text = catalogue.message ?? "The catalogue could not be read."; }
  else if (!hasProduct && catalogue.phase === "ready") text = "Choose a selection and press Show field.";
  if (!text) return null;
  return <div className={`status ${tone}`} role={tone === "error" ? "alert" : "status"}>{text}</div>;
}
