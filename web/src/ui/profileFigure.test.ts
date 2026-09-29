import { describe, expect, it } from "vitest";

import type { DecodedProfile } from "../api/observationWire";
import { profileFigure, qcLabel, verticalTitle } from "./profileFigure";

const profile: DecodedProfile = {
  datasetVersionId: "v", platformId: "5907085", cycle: "32",
  verticalKind: "pressure", verticalUnits: "decibar", verticalPositive: "down",
  vertical: new Float64Array([0.1, 0.8, 1.8]), verticalMissing: new Uint8Array([0, 0, 0]),
  timestamps: ["2024-09-02T10:00:00", "2024-09-02T10:00:00", "2024-09-02T10:00:00"],
  variables: [
    { name: "TEMP", units: "degree_Celsius", values: new Float64Array([28.9, 28.9, NaN]),
      missing: new Uint8Array([0, 1, 0]), qcFlags: ["1", "4", null],
      qcMeanings: new Map([["1", "good data"], ["4", "bad data"]]), qcConventions: "Argo reference table 2" },
    { name: "PSAL", units: "PSU", values: new Float64Array([36.0, 36.1, 36.2]),
      missing: new Uint8Array([0, 0, 0]), qcFlags: ["1", "1", "1"], qcMeanings: null, qcConventions: null },
  ],
};

describe("profileFigure", () => {
  it("labels the vertical axis with its real kind and units and points it down", () => {
    const { layout } = profileFigure(profile);
    expect(verticalTitle(profile)).toBe("Pressure (decibar)");
    expect(layout.yaxis).toMatchObject({ title: { text: "Pressure (decibar)" }, autorange: "reversed" });
  });

  it("draws one panel per variable sharing the vertical axis", () => {
    const { data, layout } = profileFigure(profile);
    expect(data.map((t) => [t.name, t.xaxis, t.yaxis])).toEqual([["TEMP", "x", "y"], ["PSAL", "x2", "y"]]);
    expect(layout.xaxis2).toMatchObject({ title: { text: "PSAL (PSU)" } });
  });

  it("leaves missing and non-finite values as gaps, never zeros", () => {
    const { data } = profileFigure(profile);
    expect(data[0].x).toEqual([28.9, null, null]);
    expect(data[0].connectgaps).toBe(false);
  });

  it("states QC meanings only where the source declared them", () => {
    const [temp, psal] = profile.variables;
    expect(qcLabel(temp, 0)).toBe("QC 1 (good data)");
    expect(qcLabel(temp, 1)).toBe("QC 4 (bad data)");
    expect(qcLabel(temp, 2)).toBe("QC missing");
    expect(qcLabel(psal, 0)).toBe("QC 1 (meaning not declared by the source)");
  });
});
