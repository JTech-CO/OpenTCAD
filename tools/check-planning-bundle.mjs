import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const roadmapPath = join(projectRoot, "03_MILESTONE_ROADMAP_KR.md");
const masterPath = join(projectRoot, "TCAD_CROSS_PLATFORM_MASTER_PLAN_KR.md");
const manifestPath = join(projectRoot, "PLANNING_BUNDLE_SHA256.txt");
const errors = [];

const roadmap = await readFile(roadmapPath, "utf8");
const master = await readFile(masterPath, "utf8");

const schedulePatterns = [
  [/\*\*예상 기간:\*\*/, "estimated-duration preface"],
  [/\| Milestone \| 기간 \|/, "roadmap duration column"],
  [/^\*\*기간:\*\*/m, "milestone duration field"],
  [/^\| M[0-8] \| \d+[–-]\d+주 \|/m, "week estimate in the milestone table"],
  [/^## \d+\. 병렬화 계획/m, "staffing parallelization plan"],
  [/^## \d+\. 일정 변동 요인/m, "schedule-variance section"],
  [/^\d+명만 수행.*\d+[–-]\d+주/m, "staffing-based week estimate"],
];

for (const [pattern, label] of schedulePatterns) {
  if (pattern.test(roadmap)) errors.push(`Roadmap still contains ${label}.`);
}

const begin = "<!-- BEGIN: 03_MILESTONE_ROADMAP_KR.md -->";
const end = "<!-- END: 03_MILESTONE_ROADMAP_KR.md -->";
const beginIndex = master.indexOf(begin);
const endIndex = master.indexOf(end);

if (beginIndex < 0 || endIndex <= beginIndex) {
  errors.push("The master plan is missing the roadmap boundary markers.");
} else {
  const embedded = master.slice(beginIndex + begin.length, endIndex).trim();
  if (embedded !== roadmap.trim()) errors.push("The roadmap and its master-plan section differ.");
}

const manifest = await readFile(manifestPath, "utf8");
const manifestLines = manifest.split(/\r?\n/).filter(Boolean);

for (const line of manifestLines) {
  const match = line.match(/^([0-9a-f]{64})  \.\/(.+)$/);
  if (!match) {
    errors.push(`Invalid planning manifest line: ${line}`);
    continue;
  }

  const [, expected, relativePath] = match;
  try {
    const bytes = await readFile(join(projectRoot, relativePath));
    const actual = createHash("sha256").update(bytes).digest("hex");
    if (actual !== expected) errors.push(`${relativePath} does not match the planning manifest.`);
  } catch {
    errors.push(`Planning manifest file is missing: ${relativePath}`);
  }
}

if (errors.length > 0) {
  console.error("Planning bundle check failed:");
  errors.forEach((error) => console.error(`- ${error}`));
  process.exitCode = 1;
} else {
  console.log(`Planning bundle check passed (${manifestLines.length} hashed artifacts, no calendar estimates).`);
}
