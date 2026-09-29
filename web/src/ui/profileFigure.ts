// The profile chart as data: one panel per variable against the shared
// vertical axis, which points down when the source's vertical is positive
// down. Pure, so what the chart claims can be tested without a browser.

import type { DecodedProfile, ProfileVariable } from "../api/observationWire";

export interface Figure {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
}

const AXIS_COLOUR = "#8ea3b7";

/** How a QC flag reads to a person: its declared meaning, or honestly none. */
export function qcLabel(variable: ProfileVariable, level: number): string {
  const flag = variable.qcFlags?.[level];
  if (variable.qcFlags === null) return "no QC variable";
  if (flag === null || flag === undefined || flag === "") return "QC missing";
  const meaning = variable.qcMeanings?.get(flag);
  return meaning ? `QC ${flag} (${meaning})` : `QC ${flag} (meaning not declared by the source)`;
}

export function verticalTitle(profile: DecodedProfile): string {
  const kind = profile.verticalKind === "pressure" ? "Pressure" : "Depth";
  return profile.verticalUnits ? `${kind} (${profile.verticalUnits})` : kind;
}

export function profileFigure(profile: DecodedProfile): Figure {
  const vertical = Array.from(profile.vertical, (v, i) => (profile.verticalMissing[i] ? null : v));
  const count = profile.variables.length;
  const data = profile.variables.map((variable, panel) => ({
    type: "scatter",
    mode: "lines+markers",
    name: variable.name,
    xaxis: panel === 0 ? "x" : `x${panel + 1}`,
    yaxis: "y",
    // Missing measurements become gaps, never zeros or interpolated values.
    x: Array.from(variable.values, (v, i) => (variable.missing[i] || !Number.isFinite(v) ? null : v)),
    y: vertical,
    connectgaps: false,
    text: vertical.map((_, i) => qcLabel(variable, i)),
    hovertemplate: `%{x} ${variable.units ?? ""}<br>${verticalTitle(profile)}: %{y}<br>%{text}<extra>${variable.name}</extra>`,
    marker: { size: 5 },
    line: { width: 1.5 },
  }));
  const layout: Record<string, unknown> = {
    grid: { rows: 1, columns: count, pattern: "independent" },
    showlegend: false,
    margin: { l: 64, r: 16, t: 24, b: 48 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#dbe6f0", size: 12 },
    yaxis: {
      title: { text: verticalTitle(profile) },
      autorange: profile.verticalPositive === "down" ? "reversed" : true,
      gridcolor: "#1d3247", color: AXIS_COLOUR, zeroline: false,
    },
  };
  profile.variables.forEach((variable, panel) => {
    layout[panel === 0 ? "xaxis" : `xaxis${panel + 1}`] = {
      title: { text: variable.units ? `${variable.name} (${variable.units})` : variable.name },
      gridcolor: "#1d3247", color: AXIS_COLOUR, zeroline: false,
    };
    if (panel > 0) layout[`yaxis${panel + 1}`] = { matches: "y", showticklabels: false };
  });
  return { data, layout };
}
