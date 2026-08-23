import type { MessageKey } from "./i18n";

export type ProfileField = "netActive" | "boron" | "arsenic" | "electrons";
export type WorkspaceView = "process" | "device" | "compare" | "runtime";
export type RunState = "idle" | "running" | "complete";

export const DEMO_DECK = `# Illustrative only — this static preview never executes input
title "OpenTCAD planar NMOS reference"

initialize silicon orientation=100
grid x=0.00 spacing=0.10
grid x=1.20 spacing=0.05
grid y=0.00 spacing=0.02
grid y=0.80 spacing=0.08

deposit oxide thickness=0.020
implant boron dose=2.0e12 energy=25
diffuse temperature=950 time=20
deposit polysilicon thickness=0.180
implant arsenic dose=5.0e15 energy=45

structure output="reference-preview.str"
`;

export const workspaceViews: Array<{
  id: WorkspaceView;
  label: MessageKey;
  marker: string;
}> = [
  { id: "process", label: "process", marker: "01" },
  { id: "device", label: "device", marker: "02" },
  { id: "compare", label: "compare", marker: "03" },
  { id: "runtime", label: "runtime", marker: "04" },
];

export const workflowSteps: MessageKey[] = [
  "sourceDeck",
  "processStage",
  "structureStage",
  "deviceStage",
  "analysisStage",
];

export const profileFields: Array<{
  id: ProfileField;
  label: MessageKey;
  color: string;
}> = [
  { id: "netActive", label: "netActive", color: "#f0b35a" },
  { id: "boron", label: "boron", color: "#54d6c5" },
  { id: "arsenic", label: "arsenic", color: "#ff7185" },
  { id: "electrons", label: "electrons", color: "#78a8ff" },
];

const gaussian = (x: number, center: number, width: number, amplitude: number) =>
  amplitude * Math.exp(-((x - center) ** 2) / (2 * width ** 2));

export function profileValue(field: ProfileField, depth: number): number {
  const boron = 1.4e15 + gaussian(depth, 0.48, 0.17, 2.8e17);
  const arsenic =
    gaussian(depth, 0.055, 0.028, 7.5e20) +
    gaussian(depth, 0.22, 0.075, 1.4e18) +
    1.0e14;
  const electrons = Math.max(2.0e14, arsenic * 0.76 - boron * 0.42);
  const netActive = Math.max(1.0e14, Math.abs(arsenic - boron));

  return { netActive, boron, arsenic, electrons }[field];
}

export const gateSweeps = [0.4, 0.6, 0.8, 1.0] as const;

export function drainCurrent(gateVoltage: number, drainVoltage: number): number {
  const threshold = 0.34;
  const overdrive = Math.max(0, gateVoltage - threshold);
  const saturation = 0.28 + overdrive * 0.72;
  const linear = overdrive * drainVoltage * (1 - 0.34 * drainVoltage);
  const pinched = overdrive ** 2 * 0.55 * (1 + 0.045 * drainVoltage);
  const blend = Math.min(1, drainVoltage / Math.max(0.12, saturation));
  return Math.max(0, linear * (1 - blend) + pinched * blend);
}
