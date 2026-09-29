// The profile chart as data: one panel per variable against the shared
// vertical axis, which points down when the source's vertical is positive
// down. Pure, so what the chart claims can be tested without a browser.

import type { DecodedProfile, ProfileVariable } from "../api/observationWire";
import { displayUnits } from "./surfaceFormat";

export interface Figure {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
}

const AXIS_COLOUR = "#8ea3b7";

/** Argo and CF variable names as people read them. */
const NAMES: Record<string, string> = {
  TEMP: "Temperature", PSAL: "Salinity", PRES: "Pressure", DOXY: "Oxygen", CHLA: "Chlorophyll",
  sea_water_temperature: "Temperature", sea_water_salinity: "Salinity",
};
const COLOURS: Record<string, string> = { Temperature: "#f59f5a", Salinity: "#4fc3f7" };

export function variableLabel(variable: ProfileVariable): string {
  return NAMES[variable.name] ?? variable.name;
}

function axisTitle(variable: ProfileVariable): string {
  const units = variable.units ? displayUnits(variable.units) : "";
  return units && units !== "1e-3" && units !== "psu" ? `${variableLabel(variable)} (${units})`
    : units ? `${variableLabel(variable)} (PSU)` : variableLabel(variable);
}

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

/** One panel per shown variable against the shared vertical axis. */
export function profileFigure(profile: DecodedProfile, shown?: readonly string[]): Figure {
  const vertical = Array.from(profile.vertical, (v, i) => (profile.verticalMissing[i] ? null : v));
  const variables = profile.variables.filter((v) => !shown || shown.includes(v.name));
  const count = variables.length;
  const data = variables.map((variable, panel) => ({
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
    hovertemplate: `%{x:.3f} · %{y:.0f} ${profile.verticalUnits ?? ""}<br>%{text}<extra></extra>`,
    marker: { size: 4, color: COLOURS[variableLabel(variable)] ?? "#9fd3ea" },
    line: { width: 2, color: COLOURS[variableLabel(variable)] ?? "#9fd3ea" },
  }));
  const layout: Record<string, unknown> = {
    grid: { rows: 1, columns: count, pattern: "independent" },
    showlegend: false,
    margin: { l: 60, r: 12, t: 12, b: 44 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "#dbe6f0", size: 12 },
    yaxis: {
      title: { text: verticalTitle(profile) },
      autorange: profile.verticalPositive === "down" ? "reversed" : true,
      gridcolor: "#1d3247", color: AXIS_COLOUR, zeroline: false,
    },
  };
  variables.forEach((variable, panel) => {
    layout[panel === 0 ? "xaxis" : `xaxis${panel + 1}`] = {
      title: { text: axisTitle(variable), font: { color: COLOURS[variableLabel(variable)] ?? "#dbe6f0" } },
      gridcolor: "#1d3247", color: AXIS_COLOUR, zeroline: false,
    };
    if (panel > 0) layout[`yaxis${panel + 1}`] = { matches: "y", showticklabels: false };
  });
  return { data, layout };
}
