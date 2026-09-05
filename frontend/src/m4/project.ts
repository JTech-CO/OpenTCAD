import { DEMO_DECK } from "../demo";
import type { MessageKey } from "../i18n";
import { boundedNumber, boundedText, exactRecord, parseWorkspaceJson, WorkspaceFileError } from "./files";

export const MAX_DECK_LENGTH = 65536;
export interface Bias { gateVoltage: number; drainVoltage: number; temperature: number }
export interface WorkspaceProject {
  format: "opentcad-project";
  schemaVersion: 1;
  name: string;
  deck: string;
  bias: Bias;
}
export const newProject = (): WorkspaceProject => ({
  format: "opentcad-project", schemaVersion: 1, name: "Planar NMOS",
  deck: DEMO_DECK, bias: { gateVoltage: 0.8, drainVoltage: 1, temperature: 300 },
});

export function validateProject(value: unknown): WorkspaceProject {
  const project = exactRecord(value, ["format", "schemaVersion", "name", "deck", "bias"]);
  if (project.format !== "opentcad-project" || project.schemaVersion !== 1
    || typeof project.deck !== "string" || project.deck.length > MAX_DECK_LENGTH
    || project.deck.includes("\0")) throw new WorkspaceFileError();
  const bias = exactRecord(project.bias, ["gateVoltage", "drainVoltage", "temperature"]);
  return {
    format: "opentcad-project", schemaVersion: 1,
    name: boundedText(project.name, 80), deck: project.deck,
    bias: {
      gateVoltage: boundedNumber(bias.gateVoltage, -10, 10),
      drainVoltage: boundedNumber(bias.drainVoltage, -10, 10),
      temperature: boundedNumber(bias.temperature, 1, 1500),
    },
  };
}
export const parseProject = (source: string) => validateProject(parseWorkspaceJson(source));
export const serializeProject = (project: WorkspaceProject) => `${JSON.stringify(validateProject(project), null, 2)}\n`;
export function projectValid(project: WorkspaceProject): boolean {
  try { validateProject(project); return true; } catch { return false; }
}

export interface DeckDiagnostic { line: number; severity: "error" | "warning"; code: MessageKey }
const rules: Record<string, string[]> = {
  initialize: ["orientation"], grid: ["spacing"], deposit: ["thickness"],
  implant: ["dose", "energy"], diffuse: ["temperature", "time"], structure: ["output"],
};

/** A small illustrative-deck lint, never a SUPREM parser or execution approval. */
export function validateDeck(deck: string): DeckDiagnostic[] {
  const issues: DeckDiagnostic[] = [];
  const add = (line: number, code: MessageKey, severity: "error" | "warning" = "error") => issues.push({ line, code, severity });
  if (!deck.trim()) { add(1, "deckEmpty"); return issues; }
  if (deck.length > MAX_DECK_LENGTH || deck.split("\n").length > 2000 || deck.includes("\0")) { add(1, "deckLimit"); return issues; }
  const seen = new Set<string>();
  deck.split(/\r?\n/).forEach((line, index) => {
    const tokens: string[] = [];
    let word = "", quote = false, escaped = false;
    for (const character of line) {
      if (character === "#" && !quote) break;
      if (character === '"' && !escaped) quote = !quote;
      if (/\s/u.test(character) && !quote) { if (word) tokens.push(word); word = ""; }
      else word += character;
      escaped = character === "\\" && !escaped;
    }
    if (word) tokens.push(word);
    if (!tokens.length) return;
    if (quote) { add(index + 1, "deckQuotes"); return; }
    const command = tokens.shift()!.toLowerCase();
    seen.add(command);
    if (["shell", "system", "exec", "include", "source"].includes(command) || /^[!$]/u.test(command)) {
      add(index + 1, "deckExternal"); return;
    }
    if (command === "title") { if (tokens.length !== 1) add(index + 1, "deckParameters"); return; }
    if (!Object.hasOwn(rules, command)) { add(index + 1, "deckUnsupported", "warning"); return; }
    const fields = new Map<string, string>();
    const positional = ["initialize", "deposit", "implant"].includes(command);
    if (positional && (!tokens[0] || tokens.shift()!.includes("="))) add(index + 1, "deckParameters");
    for (const token of tokens) {
      const match = /^([a-z]+)=(.+)$/iu.exec(token);
      if (!match || fields.has(match[1].toLowerCase())) { add(index + 1, "deckParameters"); continue; }
      fields.set(match[1].toLowerCase(), match[2]);
    }
    if (rules[command].some((key) => !fields.has(key))) add(index + 1, "deckParameters");
    if (command === "grid" && Number(fields.has("x")) + Number(fields.has("y")) !== 1) add(index + 1, "deckParameters");
    for (const [key, raw] of fields) {
      if (key === "output") continue;
      if (!["x", "y", "spacing", "orientation", "thickness", "dose", "energy", "temperature", "time"].includes(key)) {
        add(index + 1, "deckUnsupported", "warning"); continue;
      }
      const value = Number(raw);
      if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/iu.test(raw)
        || !Number.isFinite(value) || value < 0 || (!["x", "y"].includes(key) && value === 0)) add(index + 1, "deckNumeric");
    }
  });
  if (!seen.has("initialize") || !seen.has("structure")) add(1, "deckRequired");
  // Keep errors visible even when many earlier warnings hit the display cap.
  return [...issues.filter((issue) => issue.severity === "error"),
    ...issues.filter((issue) => issue.severity === "warning")].slice(0, 100);
}
