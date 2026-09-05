import { useState } from "react";
import type { MessageKey } from "../i18n";
import { downloadProject, readWorkspaceFile } from "./files";
import { parseProject, projectValid, serializeProject, type WorkspaceProject } from "./project";

interface Props {
  project: WorkspaceProject; locked: boolean;
  onChange: (project: WorkspaceProject) => void;
  text: (key: MessageKey) => string;
}
export function ProjectTools({ project, locked, onChange, text }: Props) {
  const [pending, setPending] = useState<WorkspaceProject | null>(null);
  const [reading, setReading] = useState(false);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  return (
    <section className="project-tools" aria-label={text("projectTools")}>
      <div className="m4-toolbar">
        <label className="project-name-field">{text("projectName")}
          <input value={project.name} maxLength={80} disabled={locked}
            aria-invalid={!project.name.trim()}
            onChange={(event) => onChange({ ...project, name: event.target.value })} />
        </label>
        <button type="button" className="quiet-button" disabled={!projectValid(project)} onClick={() => {
          try { downloadProject(serializeProject(project)); setNotice("projectSaved"); }
          catch { setNotice("invalidFile"); }
        }}>{text("saveProject")}</button>
        <label className="file-field">{text("openProject")}
          <input type="file" accept=".json,application/json" disabled={locked || reading}
            onChange={async (event) => {
              const file = event.target.files?.[0]; event.target.value = "";
              if (!file) return;
              setReading(true); setNotice(null); setPending(null);
              try { setPending(parseProject(await readWorkspaceFile(file))); }
              catch { setNotice("invalidFile"); }
              finally { setReading(false); }
            }} />
        </label>
      </div>
      <p className="m4-help">{text("projectFileHelp")}</p>
      {!projectValid(project) && <p role="alert">{text("projectInvalid")}</p>}
      <p role={notice === "invalidFile" ? "alert" : "status"}>{reading ? text("readingFile") : notice ? text(notice) : ""}</p>
      {pending && <div className="import-review" role="region" aria-label={text("projectImportReview")}>
        <strong>{pending.name}</strong><p>{text("projectImportReview")}</p>
        <p>{text("gateVoltage")}: {pending.bias.gateVoltage} V · {text("drainVoltage")}: {pending.bias.drainVoltage} V · {text("temperature")}: {pending.bias.temperature} K</p>
        <details><summary>{text("illustrativeDeck")}</summary><pre className="pending-deck">{pending.deck}</pre></details>
        <div className="m4-toolbar">
          <button type="button" className="quiet-button" disabled={locked} onClick={() => {
            onChange(pending); setPending(null); setNotice("projectApplied");
          }}>{text("applyProject")}</button>
          <button type="button" className="quiet-button" onClick={() => setPending(null)}>{text("discardImport")}</button>
        </div>
      </div>}
    </section>
  );
}
