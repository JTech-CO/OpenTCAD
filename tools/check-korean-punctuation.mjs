import { readFile, readdir } from "node:fs/promises";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const emDash = "\u2014";

const koreanDocuments = [
  "README.ko.md",
  "validation/README.ko.md",
];

async function markdownFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await markdownFiles(path)));
    else if (entry.isFile() && entry.name.endsWith(".md")) files.push(path);
  }

  return files;
}

const paths = [
  ...koreanDocuments.map((path) => join(projectRoot, path)),
  ...(await markdownFiles(join(projectRoot, "docs", "ko"))),
];

const violations = [];

for (const path of [...new Set(paths)]) {
  const text = await readFile(path, "utf8");
  text.split(/\r?\n/).forEach((line, index) => {
    if (line.includes(emDash)) {
      violations.push(`${relative(projectRoot, path)}:${index + 1}`);
    }
  });
}

const i18nPath = join(projectRoot, "frontend", "src", "i18n.ts");
const i18n = await readFile(i18nPath, "utf8");
const koreanStart = i18n.indexOf("export const ko:");
const koreanEnd = i18n.indexOf("export const messages", koreanStart);

if (koreanStart < 0 || koreanEnd < 0) {
  throw new Error("Could not locate the maintained Korean translation block.");
}

i18n
  .slice(koreanStart, koreanEnd)
  .split(/\r?\n/)
  .forEach((line, index) => {
    if (line.includes(emDash)) {
      const absoluteLine = i18n.slice(0, koreanStart).split(/\r?\n/).length + index;
      violations.push(`frontend/src/i18n.ts:${absoluteLine}`);
    }
  });

if (violations.length > 0) {
  console.error("Korean copy contains Unicode em dash punctuation:");
  violations.forEach((violation) => console.error(`- ${violation}`));
  process.exitCode = 1;
} else {
  console.log(`Korean punctuation check passed (${paths.length} documents plus UI translations).`);
}
