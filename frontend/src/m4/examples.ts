import type { WorkspaceResult } from "./results";

/** User-downloadable examples are illustrative, never solver or approval evidence. */
export const resultExamples: WorkspaceResult[] = [
  { format: "opentcad-result", schemaVersion: 1, kind: "iv", name: "Illustrative I-V",
    source: "OpenTCAD M4 format example; not solver output", xUnit: "V", yUnit: "mA/um",
    points: [[0, 0], [0.2, 0.04], [0.4, 0.065], [0.6, 0.076], [0.8, 0.079], [1, 0.081]] },
  { format: "opentcad-result", schemaVersion: 1, kind: "profile", name: "Illustrative depth profile",
    source: "OpenTCAD M4 format example; not solver output", xUnit: "um", yUnit: "cm^-3",
    points: [[0, 1e20], [0.1, 2e19], [0.2, 4e17], [0.4, 2e16], [0.8, 1e15]] },
  { format: "opentcad-result", schemaVersion: 1, kind: "structure", name: "Illustrative material map",
    source: "OpenTCAD M4 format example; not solver output", unit: "um", width: 1.2, height: 0.8,
    regions: [
      { id: "substrate", material: "silicon", x: 0, y: 0.24, width: 1.2, height: 0.56 },
      { id: "oxide", material: "oxide", x: 0, y: 0.21, width: 1.2, height: 0.03 },
      { id: "gate", material: "polysilicon", x: 0.46, y: 0.05, width: 0.28, height: 0.16 },
      { id: "source", material: "n+ silicon", x: 0.1, y: 0.24, width: 0.3, height: 0.14 },
      { id: "drain", material: "n+ silicon", x: 0.8, y: 0.24, width: 0.3, height: 0.14 },
    ] },
];
