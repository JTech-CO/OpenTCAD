export const MAX_FILE_BYTES = 1_048_576;

export class WorkspaceFileError extends Error {
  constructor() { super("Invalid or unsupported workspace file"); }
}

/** Bounded JSON with duplicate-key rejection, including escaped key aliases. */
export function parseWorkspaceJson(source: string): unknown {
  if (new TextEncoder().encode(source).length > MAX_FILE_BYTES) throw new WorkspaceFileError();
  let cursor = 0;
  let nodes = 0;
  const fail = (): never => { throw new WorkspaceFileError(); };
  const whitespace = () => { while (/[\t\n\r ]/.test(source[cursor] ?? "!") ) cursor++; };
  const string = (): string => {
    const start = cursor++;
    while (cursor < source.length) {
      const character = source[cursor++];
      if (character === "\\") { cursor++; continue; }
      if (character === '"') {
        try { return JSON.parse(source.slice(start, cursor)) as string; } catch { return fail(); }
      }
    }
    return fail();
  };
  const value = (depth: number): unknown => {
    if (depth > 12 || ++nodes > 25000) return fail();
    whitespace();
    const character = source[cursor];
    if (character === '"') return string();
    if (character === "{" || character === "[") {
      cursor++;
      const object = character === "{";
      const close = object ? "}" : "]";
      const record: Record<string, unknown> = Object.create(null);
      const array: unknown[] = [];
      whitespace();
      if (source[cursor] === close) { cursor++; return object ? record : array; }
      while (cursor < source.length) {
        whitespace();
        if (object) {
          if (source[cursor] !== '"') return fail();
          const key = string();
          if (Object.hasOwn(record, key) || ["__proto__", "prototype", "constructor"].includes(key)) return fail();
          whitespace();
          if (source[cursor++] !== ":") return fail();
          record[key] = value(depth + 1);
        } else array.push(value(depth + 1));
        whitespace();
        if (source[cursor] === close) { cursor++; return object ? record : array; }
        if (source[cursor++] !== ",") return fail();
      }
      return fail();
    }
    const token = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(source.slice(cursor));
    if (!token) return fail();
    cursor += token[0].length;
    const parsed: unknown = JSON.parse(token[0]);
    if (typeof parsed === "number" && !Number.isFinite(parsed)) return fail();
    return parsed;
  };
  const parsed = value(0);
  whitespace();
  if (cursor !== source.length) return fail();
  return parsed;
}

export function exactRecord(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).sort().join("|") !== [...keys].sort().join("|")) throw new WorkspaceFileError();
  return value as Record<string, unknown>;
}

export function boundedText(value: unknown, limit: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > limit
    || Array.from(value).some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) throw new WorkspaceFileError();
  return value;
}

export function boundedNumber(value: unknown, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) throw new WorkspaceFileError();
  return value;
}

export function readWorkspaceBytes(file: File): Promise<ArrayBuffer> {
  if (file.size > MAX_FILE_BYTES) return Promise.reject(new WorkspaceFileError());
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new WorkspaceFileError());
    reader.onabort = () => reject(new WorkspaceFileError());
    reader.onload = () => reader.result instanceof ArrayBuffer ? resolve(reader.result) : reject(new WorkspaceFileError());
    reader.readAsArrayBuffer(file);
  });
}

export function decodeWorkspaceText(bytes: ArrayBuffer): string {
  try { return new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new WorkspaceFileError(); }
}

export async function readWorkspaceFile(file: File): Promise<string> {
  return decodeWorkspaceText(await readWorkspaceBytes(file));
}

export function downloadWorkspaceJson(source: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([source], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const downloadProject = (source: string) => downloadWorkspaceJson(source, "opentcad-project.json");
