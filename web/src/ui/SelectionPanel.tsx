// Dataset, variable, time, region, depth and density selection
// (IMAP s7-selection-controls). Produces a request only on "Show field".

import type { CatalogueVersion } from "../api/client";
import type { Selection, State } from "../state/store";

interface Props {
  catalogue: State["catalogue"];
  selection: Selection | null;
  loading: boolean;
  maximumPoints: number;
  onSelectVersion: (id: string) => void;
  onEdit: (patch: Partial<Omit<Selection, "versionId">>) => void;
  onShow: () => void;
}

function label(version: CatalogueVersion): string {
  return `${version.dataset} · ${version.extent.time_start?.slice(0, 16).replace("T", " ") ?? "?"}`;
}

function NumberField(props: { label: string; value: number; step?: number; onChange: (v: number) => void }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      <input type="number" value={props.value} step={props.step ?? "any"}
        onChange={(e) => Number.isFinite(e.target.valueAsNumber) && props.onChange(e.target.valueAsNumber)} />
    </label>
  );
}

export function SelectionPanel({ catalogue, selection, loading, maximumPoints, onSelectVersion, onEdit, onShow }: Props) {
  if (catalogue.phase !== "ready" || !selection) {
    return <section className="panel"><h2>Data</h2><p className="muted">
      {catalogue.phase === "loading" ? "Loading the catalogue…"
        : catalogue.phase === "failed" ? catalogue.message
        : "No model fields are stored yet."}</p></section>;
  }
  const version = catalogue.versions.find((v) => v.id === selection.versionId)!;
  const times = version.time_values ?? (version.extent.time_start ? [version.extent.time_start] : []);
  return (
    <section className="panel" aria-label="Data selection">
      <h2>Data</h2>
      <label className="field wide">
        <span>Dataset version</span>
        <select value={selection.versionId} onChange={(e) => onSelectVersion(e.target.value)}>
          {catalogue.versions.map((v) => <option key={v.id} value={v.id}>{label(v)}</option>)}
        </select>
      </label>
      <label className="field wide">
        <span>Variable</span>
        <select value={selection.variable} onChange={(e) => onEdit({ variable: e.target.value })}>
          {version.variables.map((v) => <option key={v.name} value={v.name}>{v.name}{v.units ? ` (${v.units})` : ""}</option>)}
        </select>
      </label>
      <label className="field wide">
        <span>Time (UTC)</span>
        <select value={selection.time} onChange={(e) => onEdit({ time: e.target.value })}>
          {times.map((t) => <option key={t} value={t}>{t.replace("T", " ").replace("+00:00", "")}</option>)}
        </select>
      </label>
      <div className="grid">
        <NumberField label="West °E" value={selection.west} onChange={(west) => onEdit({ west })} />
        <NumberField label="East °E" value={selection.east} onChange={(east) => onEdit({ east })} />
        <NumberField label="South °N" value={selection.south} onChange={(south) => onEdit({ south })} />
        <NumberField label="North °N" value={selection.north} onChange={(north) => onEdit({ north })} />
        <NumberField label="Depth from (m)" value={selection.depthMinimum} onChange={(depthMinimum) => onEdit({ depthMinimum })} />
        <NumberField label="Depth to (m)" value={selection.depthMaximum} onChange={(depthMaximum) => onEdit({ depthMaximum })} />
      </div>
      <label className="field wide">
        <span>Points to show (up to {maximumPoints.toLocaleString()})</span>
        <input type="number" min={1} max={maximumPoints} step={1000} value={selection.maximumPoints}
          onChange={(e) => Number.isFinite(e.target.valueAsNumber) && onEdit({ maximumPoints: Math.max(1, Math.round(e.target.valueAsNumber)) })} />
      </label>
      <button className="primary" onClick={onShow} disabled={loading}>{loading ? "Preparing…" : "Show field"}</button>
    </section>
  );
}
