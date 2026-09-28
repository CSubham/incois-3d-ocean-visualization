// Palette, range, scale, opacity and vertical exaggeration as persistent
// renderer state (IMAP s7-display-controls). No change here reprocesses data.

import type { Range } from "../api/wire";
import { logScaleProblem, PALETTES } from "../renderer/colour";
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

const EXAGGERATION_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];

export function DisplayPanel({ display, fullSubsetRange, enabled, onChange, onUseFullSubsetRange, onResetCamera }: Props) {
  const logProblem = logScaleProblem(display.range.minimum, display.range.maximum);
  const stepIndex = EXAGGERATION_STEPS.reduce((best, v, i) =>
    Math.abs(v - display.verticalExaggeration) < Math.abs(EXAGGERATION_STEPS[best] - display.verticalExaggeration) ? i : best, 0);
  return (
    <section className="panel" aria-label="Display">
      <h2>Display</h2>
      <fieldset disabled={!enabled}>
        <label className="field wide">
          <span>Palette</span>
          <select value={display.palette} onChange={(e) => onChange({ palette: e.target.value as PaletteName })}>
            {PALETTES.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <div className="grid">
          <label className="field">
            <span>Range min</span>
            <input type="number" step="any" value={round(display.range.minimum)}
              onChange={(e) => Number.isFinite(e.target.valueAsNumber) && onChange({ range: { ...display.range, minimum: e.target.valueAsNumber } })} />
          </label>
          <label className="field">
            <span>Range max</span>
            <input type="number" step="any" value={round(display.range.maximum)}
              onChange={(e) => Number.isFinite(e.target.valueAsNumber) && onChange({ range: { ...display.range, maximum: e.target.valueAsNumber } })} />
          </label>
        </div>
        <p className="hint">
          {display.rangeSource === "full-subset"
            ? "Range: full selected subset, before sampling."
            : "Range: custom."}{" "}
          {display.rangeSource === "custom" && fullSubsetRange?.minimum !== null && (
            <button className="link" onClick={onUseFullSubsetRange}>Use full-subset range</button>
          )}
        </p>
        <div className="segmented" role="radiogroup" aria-label="Colour scale">
          {(["linear", "log"] as ScaleKind[]).map((scale) => (
            <label key={scale} title={scale === "log" && logProblem ? logProblem : undefined}>
              <input type="radio" name="scale" value={scale} checked={display.scale === scale}
                disabled={scale === "log" && logProblem !== null}
                onChange={() => onChange({ scale })} />
              {scale === "linear" ? "Linear" : "Logarithmic"}
            </label>
          ))}
        </div>
        {logProblem && <p className="hint">Logarithmic scale unavailable: {logProblem}.</p>}
        <label className="field wide">
          <span>Opacity {Math.round(display.opacity * 100)}%</span>
          <input type="range" min={0.05} max={1} step={0.05} value={display.opacity}
            onChange={(e) => onChange({ opacity: e.target.valueAsNumber })} />
        </label>
        <label className="field wide">
          <span>Vertical exaggeration ×{display.verticalExaggeration}</span>
          <input type="range" min={0} max={EXAGGERATION_STEPS.length - 1} step={1} value={stepIndex}
            onChange={(e) => onChange({ verticalExaggeration: EXAGGERATION_STEPS[e.target.valueAsNumber] })} />
        </label>
        <button onClick={onResetCamera}>Reset view</button>
      </fieldset>
    </section>
  );
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}
