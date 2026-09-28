// The colourbar: palette, range, scale and units of what is on screen.

import { cssGradient } from "../renderer/colour";
import type { Display } from "../state/store";

export function Colourbar({ display, units, variable }: { display: Display; units: string; variable: string }) {
  const { minimum, maximum } = display.range;
  const middle = display.scale === "log" ? Math.sqrt(minimum * maximum) : (minimum + maximum) / 2;
  const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toPrecision(3));
  return (
    <figure className="colourbar" aria-label={`Colour scale for ${variable}`}>
      <figcaption>{variable} ({units}) · {display.scale}</figcaption>
      <div className="bar" style={{ background: cssGradient(display.palette) }} />
      <div className="ticks"><span>{fmt(minimum)}</span><span>{fmt(middle)}</span><span>{fmt(maximum)}</span></div>
    </figure>
  );
}
