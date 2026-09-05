import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  DEMO_DECK,
  gateSweeps,
  profileFields,
  workflowSteps,
  workspaceViews,
  type ProfileField,
  type RunState,
  type WorkspaceView,
} from "./demo";
import {
  getInitialLocale,
  messages,
  type Locale,
  type MessageKey,
} from "./i18n";
import { IvCanvas, ProfileCanvas } from "./components/ScientificCanvas";
import { DeviceCrossSection } from "./components/DeviceCrossSection";
import { ProjectTools } from "./m4/ProjectTools";
import { ResultsWorkbench } from "./m4/ResultsWorkbench";
import { MAX_DECK_LENGTH, newProject, projectValid, validateDeck, type WorkspaceProject } from "./m4/project";
import { initialMockRun, mockReducer, type MockRun } from "./m4/mock-workflow";
import type { ImportedResult } from "./m4/results";
import "./m4/workspace.css";
import { LandingPage } from "./LandingPage";
import {
  fetchLocalProductStatus,
  type LocalProductStatus,
  type LocalServiceBootstrap,
  type ProductGateId,
} from "./local-service";

const repositoryUrl = "https://github.com/JTech-CO/OpenTCAD";
const productGateLabelKeys: Record<ProductGateId, MessageKey> = {
  "runtime-adapters": "gateRuntimeAdapters",
  "native-fencing": "gateNativeFencing",
  "local-transport": "gateLocalTransport",
  "lifecycle-integration": "gateLifecycleIntegration",
  "credentials-and-scheduler": "gateCredentialsScheduler",
  "power-loss": "gatePowerLoss",
  "platform-qualification": "gatePlatformQualification",
  "solver-release": "gateSolverRelease",
};
type AppSurface = "intro" | "workspace";
type LocalConnectionState =
  | "unavailable"
  | "available"
  | "connecting"
  | "connected"
  | "error";

interface AppProps {
  localBootstrap?: LocalServiceBootstrap | null;
}

function getInitialSurface(): AppSurface {
  return window.location.hash === "#workspace" ? "workspace" : "intro";
}

function App({ localBootstrap = null }: AppProps) {
  const [locale, setLocale] = useState<Locale>(getInitialLocale);
  const [surface, setSurface] = useState<AppSurface>(getInitialSurface);
  const [view, setView] = useState<WorkspaceView>("process");
  const [project, setProject] = useState(newProject);
  const deck = project.deck;
  const [results, setResults] = useState<ImportedResult[]>([]);
  const [selectedField, setSelectedField] =
    useState<ProfileField>("netActive");
  const [mockRun, dispatchMock] = useReducer(mockReducer, initialMockRun);
  const runState = mockRun.phase;
  const activeStep = mockRun.step;
  const locked = runState === "running" || runState === "interrupted";
  const changeProject = (next: WorkspaceProject) => {
    if (locked) return;
    setProject(next); dispatchMock({ type: "reset" });
  };
  const setDeck = (value: string) => changeProject({ ...project, deck: value });
  const [localConnection, setLocalConnection] = useState<LocalConnectionState>(
    localBootstrap ? "available" : "unavailable",
  );
  const [localStatus, setLocalStatus] = useState<LocalProductStatus | null>(null);
  const copy = messages[locale];
  const text = (key: MessageKey) => copy[key];

  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      window.localStorage.setItem("opentcad-locale", locale);
    } catch {
      // Locale persistence is optional; the UI remains fully usable without it.
    }
  }, [locale]);

  useEffect(() => {
    const syncSurface = () => {
      setSurface(window.location.hash === "#workspace" ? "workspace" : "intro");
    };

    window.addEventListener("hashchange", syncSurface);
    return () => window.removeEventListener("hashchange", syncSurface);
  }, []);

  useEffect(() => {
    if (surface !== "workspace" || runState !== "running") {
      return;
    }

    const timer = window.setTimeout(() => {
      dispatchMock({ type: "tick", generation: mockRun.generation });
    }, 620);

    return () => window.clearTimeout(timer);
  }, [activeStep, runState, surface, mockRun.generation]);

  const lineCount = useMemo(
    () => deck.split(/\r?\n/).length,
    [deck],
  );

  const progress =
    runState === "idle"
      ? 0
      : runState === "complete"
        ? 100
        : Math.round(((activeStep + 1) / workflowSteps.length) * 100);

  const startReferenceRun = () => {
    if (projectValid(project) && !validateDeck(deck).some((issue) => issue.severity === "error")) dispatchMock({ type: "start" });
  };

  const connectLocalService = async () => {
    if (!localBootstrap || localConnection === "connecting") {
      return;
    }
    setLocalConnection("connecting");
    try {
      setLocalStatus(await fetchLocalProductStatus(localBootstrap));
      setLocalConnection("connected");
    } catch {
      setLocalStatus(null);
      setLocalConnection("error");
    }
  };

  const localSurface = localBootstrap !== null;
  const localAuthorized = localStatus?.executionState === "authorized";

  const openWorkspace = () => {
    window.location.hash = "workspace";
    setSurface("workspace");
  };

  const openOverview = () => {
    window.location.hash = "";
    setSurface("intro");
  };

  const titleKey: Record<WorkspaceView, MessageKey> = {
    process: "processTitle",
    device: "deviceTitle",
    compare: "compareTitle",
    runtime: "runtimeTitle",
  };
  const subtitleKey: Record<WorkspaceView, MessageKey> = {
    process: "processSubtitle",
    device: "deviceSubtitle",
    compare: "compareSubtitle",
    runtime: "runtimeSubtitle",
  };

  if (surface === "intro") {
    return (
      <LandingPage
        locale={locale}
        text={text}
        onLocaleChange={setLocale}
        onOpenWorkspace={openWorkspace}
      />
    );
  }

  return (
    <div className="app-shell" data-ui="precision-cad">
      <a className="skip-link" href="#workspace-main">
        {text("skipToMain")}
      </a>
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <div className="brand-name">OpenTCAD</div>
            <div className="brand-subtitle">{text("appSubtitle")}</div>
          </div>
        </div>

        <div className="topbar-center">
          <span className="mode-beacon" aria-hidden="true" />
          <div>
            <strong>{text(localSurface ? "localService" : "staticPreview")}</strong>
            <span>
              {text(
                localConnection === "connected"
                  ? localAuthorized
                    ? "localServiceAuthorized"
                    : "localServiceBlocked"
                  : localSurface
                    ? "localModeDetail"
                    : "staticModeDetail",
              )}
            </span>
          </div>
        </div>

        <div className="topbar-actions">
          <button type="button" className="overview-link" onClick={openOverview}>
            {text("backToOverview")}
          </button>
          <a
            className="repo-link"
            href={repositoryUrl}
            target="_blank"
            rel="noreferrer"
            aria-label={text("openRepo")}
          >
            <span>GitHub</span>
            <span aria-hidden="true">↗</span>
          </a>
          <div
            className="locale-switch"
            role="group"
            aria-label={text("language")}
          >
            <button
              type="button"
              className={locale === "en" ? "active" : ""}
              aria-pressed={locale === "en"}
              onClick={() => setLocale("en")}
            >
              EN
            </button>
            <button
              type="button"
              className={locale === "ko" ? "active" : ""}
              aria-pressed={locale === "ko"}
              onClick={() => setLocale("ko")}
            >
              한국어
            </button>
          </div>
        </div>
      </header>

      <aside className="sidebar">
        <section className="project-card" aria-label={text("referenceProject")}>
          <div className="eyebrow">{text("referenceProject")}</div>
          <div className="project-title">{project.name || text("sampleProject")}</div>
          <div className="project-meta">
            <span className="project-dot" aria-hidden="true" />
            {text("projectRevision")}
          </div>
        </section>

        <nav className="workspace-nav" aria-label={text("navigation")}>
          {workspaceViews.map((item) => (
            <button
              key={item.id}
              type="button"
              className={view === item.id ? "nav-item active" : "nav-item"}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <span className="nav-marker" aria-hidden="true">
                {item.marker}
              </span>
              <span>{text(item.label)}</span>
              <span className="nav-chevron" aria-hidden="true">
                ›
              </span>
            </button>
          ))}
        </nav>

        <details className="workflow-card">
          <summary>
            {text("workflow")}
          </summary>
          <ol className="workflow-list">
            {workflowSteps.map((step, index) => {
              const isComplete =
                runState === "complete" ||
                (runState === "running" && index < activeStep);
              const isRunning =
                runState === "running" && index === activeStep;
              return (
                <li
                  key={step}
                  className={
                    isRunning
                      ? "running"
                      : isComplete
                        ? "complete"
                        : index === 0 && runState === "idle"
                          ? "ready"
                          : ""
                  }
                >
                  <span className="step-node" aria-hidden="true">
                    {isComplete ? "✓" : String(index + 1).padStart(2, "0")}
                  </span>
                  <span>{text(step)}</span>
                  {isRunning && (
                    <span className="visually-hidden">{text("stepRunning")}</span>
                  )}
                  {isComplete && (
                    <span className="visually-hidden">{text("stepComplete")}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </details>

        <div className="education-note">
          <span className="education-icon" aria-hidden="true">
            i
          </span>
          <div>
            <strong>{text("educationalNotice")}</strong>
            <p>{text("educationalDetail")}</p>
          </div>
        </div>
      </aside>

      <main className="main-workspace" id="workspace-main">
        <div className="safety-banner" role="note">
          <div className="safety-shield" aria-hidden="true">
            <span />
          </div>
          <div>
            <strong>{text(localSurface ? "localSafetyBoundary" : "safeBoundary")}</strong>
            <p>{text(localSurface ? "localSafetyBoundaryDetail" : "safeBoundaryDetail")}</p>
          </div>
          <span className="static-stamp">
            {text(localSurface ? "localLabel" : "staticLabel")}
          </span>
        </div>

        <ProjectTools project={project} locked={locked} onChange={changeProject} text={text} />
        <div className="workspace-heading">
          <div>
            <div className="eyebrow">
              OpenTCAD / {text(view)}
            </div>
            <h1>{text(titleKey[view])}</h1>
            <p>{text(subtitleKey[view])}</p>
          </div>
          {view !== "runtime" && (
            <div className="reference-badge">
              <span className="reference-pulse" aria-hidden="true" />
              <span>
                <strong>{text(view === "compare" && results.length ? "unverifiedImport" : "referenceOnly")}</strong>
                <small>{text(view === "compare" && results.length ? "notVerifiedOutput" : "notSolverOutput")}</small>
              </span>
            </div>
          )}
        </div>

        {view === "process" && (
          <ProcessView
            locale={locale}
            deck={deck}
            lineCount={lineCount}
            selectedField={selectedField}
            runState={runState}
            progress={progress}
            text={text}
            onDeckChange={setDeck}
            onReset={() => setDeck(DEMO_DECK)}
            onFieldChange={setSelectedField}
            onRun={startReferenceRun}
            locked={locked}
            projectReady={projectValid(project)}
            mockRun={mockRun}
            onCancel={() => dispatchMock({ type: "cancel" })}
            onInterrupt={() => dispatchMock({ type: "interrupt" })}
            onRecover={() => dispatchMock({ type: "recover" })}
          />
        )}

        {view === "device" && <DeviceView text={text} project={project} locked={locked} onChange={changeProject} />}

        {view === "compare" && <div className="results-stack">
          <ResultsWorkbench records={results} onChange={setResults} text={text} />
          <details className="reference-curves"><summary>{text("referenceOnly")} · {text("ivCurves")}</summary><CompareView text={text} /></details>
        </div>}

        {view === "runtime" && (
          <RuntimeView
            locale={locale}
            text={text}
            connection={localConnection}
            status={localStatus}
            onConnect={connectLocalService}
          />
        )}
      </main>

      <details className="inspector">
        <summary>{text("runDetails")} · {text("provenance")}</summary>
        <div className="inspector-content">
          <section className="inspector-section">
            <div className="section-label">{text("runDetails")}</div>
            <div className="run-state" aria-live="polite" role="status">
              <span className={`run-state-dot ${runState}`} aria-hidden="true" />
              <div>
                <strong>{text(runState)}</strong>
                <span>mock-ui-{mockRun.generation}</span>
              </div>
            </div>
            <div className="progress-track" aria-hidden="true">
              <span style={{ width: `${progress}%` }} />
            </div>
            <dl className="detail-list">
              <div>
                <dt>{text("mode")}</dt>
                <dd>{text(localSurface ? "localService" : "staticPreview")}</dd>
              </div>
              <div>
                <dt>{text("engine")}</dt>
                <dd className="muted-value">
                  {localConnection === "connected"
                    ? localStatus?.backend ?? text("localServiceBlocked")
                    : text("disconnected")}
                </dd>
              </div>
              <div>
                <dt>{text("job")}</dt>
                <dd>{text("referenceOnly")}</dd>
              </div>
            </dl>
            <p className="inspector-help">
              {text(
                localConnection === "connected"
                  ? localAuthorized
                    ? "localServiceAuthorized"
                    : "localServiceBlocked"
                  : localSurface
                    ? "localConnectionPrompt"
                    : "engineUnavailable",
              )}
            </p>
          </section>

          <section className="inspector-section">
            <div className="section-label">{text("provenance")}</div>
            <dl className="detail-list">
              <div>
                <dt>{text("appRevision")}</dt>
                <dd>preview-r01</dd>
              </div>
              <div>
                <dt>{text("dataset")}</dt>
                <dd>{text(view === "compare" && results.length ? "unverifiedImport" : "referenceDataset")}</dd>
              </div>
            </dl>
          </section>

          <section className="guard-card">
            <span className="guard-mark" aria-hidden="true">
              ≠
            </span>
            <div>
              <strong>{text("numericalGuard")}</strong>
              <p>{text("numericalGuardDetail")}</p>
            </div>
          </section>
        </div>
      </details>
    </div>
  );
}

interface SharedTextProps {
  text: (key: MessageKey) => string;
}

interface ProcessViewProps extends SharedTextProps {
  locale: Locale;
  deck: string;
  lineCount: number;
  selectedField: ProfileField;
  runState: RunState;
  progress: number;
  onDeckChange: (value: string) => void;
  onReset: () => void;
  onFieldChange: (field: ProfileField) => void;
  onRun: () => void;
  locked: boolean;
  projectReady: boolean;
  mockRun: MockRun;
  onCancel: () => void;
  onInterrupt: () => void;
  onRecover: () => void;
}

function ProcessView({
  deck,
  lineCount,
  selectedField,
  runState,
  progress,
  text,
  onDeckChange,
  onReset,
  onFieldChange,
  onRun,
  locked, projectReady, mockRun, onCancel, onInterrupt, onRecover,
}: ProcessViewProps) {
  const editor = useRef<HTMLTextAreaElement>(null);
  const diagnostics = useMemo(() => validateDeck(deck), [deck]);
  const hasErrors = diagnostics.some((issue) => issue.severity === "error");
  return (
    <>
      <div className="process-grid">
        <section className="panel editor-panel">
          <div className="panel-header">
            <div>
              <h2>{text("illustrativeDeck")}</h2>
              <p>{text("deckDescription")}</p>
            </div>
            <button type="button" className="quiet-button" disabled={locked} onClick={onReset}>
              {text("reset")}
            </button>
          </div>
          <div className="editor-wrap">
            <div className="editor-gutter" aria-hidden="true">
              {Array.from({ length: Math.max(16, deck.split(/\r?\n/).length) }, (_, index) => (
                <span key={index}>{index + 1}</span>
              ))}
            </div>
            <textarea
              ref={editor}
              readOnly={locked}
              maxLength={MAX_DECK_LENGTH}
              aria-invalid={hasErrors}
              aria-describedby="deck-check-help"
              value={deck}
              onChange={(event) => onDeckChange(event.target.value)}
              spellCheck={false}
              aria-label={text("deckAria")}
            />
          </div>
          <div className="panel-footer">
            <span>UTF-8</span>
            <span>
              {lineCount} {text("lineCount")}
            </span>
            <span>{text("notSolverOutput")}</span>
          </div>
        </section>

        <section className="panel plot-panel">
          <div className="panel-header">
            <div>
              <h2>{text("profile")}</h2>
              <p>{text("profileSubtitle")}</p>
            </div>
            <span className="mini-badge">{text("referenceOnly")}</span>
          </div>
          <div
            className="field-selector"
            role="group"
            aria-label={text("selectField")}
          >
            {profileFields.map((field) => (
              <button
                key={field.id}
                type="button"
                className={selectedField === field.id ? "active" : ""}
                aria-pressed={selectedField === field.id}
                style={{ "--field-color": field.color } as React.CSSProperties}
                onClick={() => onFieldChange(field.id)}
              >
                <span aria-hidden="true" />
                {text(field.label)}
              </button>
            ))}
          </div>
          <div className="canvas-frame">
            <ProfileCanvas
              selectedField={selectedField}
              ariaLabel={text("profileAria")}
            />
          </div>
        </section>
      </div>

      <section className="deck-diagnostics" aria-label={text("checkDeck")}>
        <h2>{text("checkDeck")}</h2><p id="deck-check-help">{text("deckCheckHelp")}</p>
        {!diagnostics.length ? <p role="status">{text("deckValid")}</p> : <ul>
          {diagnostics.map((issue, index) => <li key={index} className={issue.severity}>
            <button type="button" onClick={() => {
              const offset = deck.split("\n").slice(0, issue.line - 1).reduce((sum, line) => sum + line.length + 1, 0);
              editor.current?.focus(); editor.current?.setSelectionRange(offset, offset + (deck.split("\n")[issue.line - 1]?.length ?? 0));
            }}>{text("lineLabel")} {issue.line} · {text(issue.severity === "error" ? "errorLabel" : "warningLabel")}: {text(issue.code)}</button>
          </li>)}
        </ul>}
      </section>
      <p className="mock-label">{text("mockMode")}</p>
      <section className="run-console">
        <div className="run-console-state" aria-live="polite">
          <span className={`run-state-dot ${runState}`} aria-hidden="true" />
          <div>
            <strong>{text(runState)}</strong>
            <span>{text("notSolverOutput")}</span>
          </div>
        </div>
        <div className="run-progress-copy">
          <span>{String(progress).padStart(3, "0")}%</span>
          <div className="progress-track" aria-hidden="true">
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
        <button
          type="button"
          className="primary-button"
          disabled={locked || hasErrors || !projectReady}
          onClick={onRun}
        >
          <span className="run-icon" aria-hidden="true">
            ▶
          </span>
          {runState === "complete"
            ? text("runAgain")
            : text("runReference")}
        </button>
      </section>
      <div className="mock-controls">
        <p>{text("mockHelp")}</p>
        <div className="m4-toolbar">
          <button type="button" className="quiet-button" disabled={!locked} onClick={onCancel}>{text("cancelMock")}</button>
          <button type="button" className="quiet-button" disabled={runState !== "running"} onClick={onInterrupt}>{text("interruptMock")}</button>
          <button type="button" className="quiet-button" disabled={runState !== "interrupted"} onClick={onRecover}>{text("recoverMock")}</button>
        </div>
        <details><summary>{text("mockEvents")}</summary><ol role="log" aria-live="polite" aria-label={text("mockEvents")}>
          {mockRun.history.map((event, index) => <li key={index}>{text(event.phase)} · {text(workflowSteps[event.step])}</li>)}
        </ol></details>
      </div>
    </>
  );
}

function DeviceView({ text, project, locked, onChange }: SharedTextProps & { project: WorkspaceProject; locked: boolean; onChange: (project: WorkspaceProject) => void }) {
  const materials: Array<[MessageKey, string]> = [
    ["silicon", "#b9d9ec"],
    ["dopedRegion", "#386cb0"],
    ["oxide", "#eee5b5"],
    ["polysilicon", "#d9a23e"],
    ["contact", "#596a78"],
  ];
  const electrodes: Array<[string, MessageKey]> = [
    ["S", "source"],
    ["G", "gate"],
    ["D", "drain"],
    ["B", "substrate"],
  ];

  return (
    <div className="device-grid">
      <section className="panel device-visual">
        <div className="panel-header">
          <div>
            <h2>{text("crossSection")}</h2>
            <p>{text("crossSectionSubtitle")}</p>
          </div>
          <span className="mini-badge">{text("referenceOnly")}</span>
        </div>
        <DeviceCrossSection text={text} />
        <div className="material-legend" aria-label={text("material")}>
          {materials.map(([label, color]) => (
            <span key={label}>
              <i style={{ backgroundColor: color }} aria-hidden="true" />
              {text(label)}
            </span>
          ))}
        </div>
      </section>

      <div className="device-controls">
        <section className="panel compact-panel">
          <div className="panel-header">
            <div>
              <h2>{text("electrodes")}</h2>
              <p>{text("referenceOnly")}</p>
            </div>
          </div>
          <div className="electrode-list">
            {electrodes.map(([symbol, electrode]) => (
              <div key={electrode}>
                <span className="electrode-index">{symbol}</span>
                <strong>{text(electrode)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel compact-panel">
          <div className="panel-header">
            <div>
              <h2>{text("biasConditions")}</h2>
              <p>{text("notSolverOutput")}</p>
            </div>
          </div>
          <div className="bias-editor">
            {(["gateVoltage", "drainVoltage", "temperature"] as const).map((key) => <label key={key}>
              {text(key)} ({key === "temperature" ? "K" : "V"})
              <input type="number" value={Number.isFinite(project.bias[key]) ? project.bias[key] : ""}
                disabled={locked} min={key === "temperature" ? 1 : -10} max={key === "temperature" ? 1500 : 10} step="any"
                onChange={(event) => onChange({ ...project, bias: { ...project.bias, [key]: event.target.valueAsNumber } })} />
            </label>)}
          </div>
        </section>
      </div>
    </div>
  );
}

function CompareView({ text }: SharedTextProps) {
  const colors = ["#6f8190", "#55c8be", "#f2b75e", "#ff7086"];

  return (
    <div className="compare-grid">
      <section className="panel curve-panel">
        <div className="panel-header">
          <div>
            <h2>{text("ivCurves")}</h2>
            <p>{text("ivSubtitle")}</p>
          </div>
          <span className="mini-badge">{text("curveCount")}</span>
        </div>
        <div className="canvas-frame">
          <IvCanvas ariaLabel={text("ivAria")} />
        </div>
      </section>

      <section className="panel sweep-panel">
        <div className="panel-header">
          <div>
            <h2>{text("gateBias")}</h2>
            <p>{text("referenceOnly")}</p>
          </div>
        </div>
        <div className="curve-list">
          {gateSweeps.map((voltage, index) => (
            <div key={voltage}>
              <span
                className="curve-swatch"
                style={{ backgroundColor: colors[index] }}
                aria-hidden="true"
              />
              <div>
                <strong>Vg = {voltage.toFixed(1)} V</strong>
                <span>{text("drainBias")} 0.0 → 1.2 V</span>
              </div>
              <span className="curve-index">C{index + 1}</span>
            </div>
          ))}
        </div>
        <div className="curve-note">
          <strong>{text("notSolverOutput")}</strong>
          <p>{text("numericalGuardDetail")}</p>
        </div>
      </section>
    </div>
  );
}

interface RuntimeViewProps extends SharedTextProps {
  locale: Locale;
  connection: LocalConnectionState;
  status: LocalProductStatus | null;
  onConnect: () => void;
}

function RuntimeView({
  locale,
  text,
  connection,
  status,
  onConnect,
}: RuntimeViewProps) {
  const path: MessageKey[] = ["browser", "api", "worker", "broker", "ociRuntime"];
  const architectureUrl = `${repositoryUrl}/blob/main/docs/${locale}/architecture.md`;
  const m3EntryGatesUrl = `${repositoryUrl}/blob/main/docs/${locale}/m3-entry-gates.md`;

  return (
    <div className="runtime-stack">
      <div className="runtime-mode-grid">
        <section className="mode-card available">
          <span className="mode-number">01</span>
          <div>
            <div className="mode-card-heading">
              <h2>{text("pagesSafe")}</h2>
              <span>{text("staticPreview")}</span>
            </div>
            <p>{text("pagesSafeDetail")}</p>
          </div>
        </section>
        <section
          className={`mode-card ${connection === "unavailable" ? "planned" : "local"}`}
          aria-busy={connection === "connecting"}
        >
          <span className="mode-number">02</span>
          <div>
            <div className="mode-card-heading">
              <h2>{text("localEngine")}</h2>
              <span>
                {text(
                  connection === "unavailable"
                    ? "notAvailableYet"
                    : connection === "connected"
                      ? status?.executionState === "authorized"
                        ? "localServiceAuthorized"
                        : "localServiceBlocked"
                      : connection === "connecting"
                        ? "connectingLocalService"
                        : connection === "error"
                          ? "localServiceError"
                          : "localServiceAvailable",
                )}
              </span>
            </div>
            <p>{text("localEngineDetail")}</p>
            <a
              className="quiet-link gate-readiness-link"
              href={m3EntryGatesUrl}
              target="_blank"
              rel="noreferrer"
            >
              {text("reviewM3EntryGates")} <span aria-hidden="true">↗</span>
            </a>
            {connection !== "unavailable" && (
              <div className="local-connection" role="status" aria-live="polite">
                {connection === "connected" && status ? (
                  <dl>
                    <div>
                      <dt>{text("transport")}</dt>
                      <dd>{text("localServiceConnected")}</dd>
                    </div>
                    <div>
                      <dt>{text("executionAuthorization")}</dt>
                      <dd>
                        {text(
                          status.executionState === "authorized"
                            ? "localServiceAuthorized"
                            : "localServiceBlocked",
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{text("gateBlockers")}</dt>
                      <dd>
                        {status.blockedGates.length > 0
                          ? (
                              <ul
                                className="gate-label-list"
                                role="list"
                                aria-label={text("gateBlockers")}
                              >
                                {status.blockedGates.map((gate) => (
                                  <li key={gate}>{text(productGateLabelKeys[gate])}</li>
                                ))}
                              </ul>
                            )
                          : text("noGateBlockers")}
                      </dd>
                    </div>
                  </dl>
                ) : (
                  <p>
                    {text(
                      connection === "error"
                        ? "localServiceError"
                        : connection === "connecting"
                          ? "connectingLocalService"
                          : "localConnectionPrompt",
                    )}
                  </p>
                )}
                {connection !== "connected" && (
                  <button
                    type="button"
                    className="primary-action local-connect-button"
                    onClick={onConnect}
                    disabled={connection === "connecting"}
                  >
                    {text(
                      connection === "error"
                        ? "retryConnection"
                        : "connectLocalService",
                    )}
                  </button>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      <section className="panel runtime-path">
        <div className="panel-header">
          <div>
            <h2>{text("plannedPath")}</h2>
            <p>{text("localEngineDetail")}</p>
          </div>
          <a
            className="quiet-link"
            href={architectureUrl}
            target="_blank"
            rel="noreferrer"
          >
            {text("readArchitecture")} ↗
          </a>
        </div>
        <ol>
          {path.map((step, index) => (
            <li key={step}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{text(step)}</strong>
              {index < path.length - 1 && <i aria-hidden="true">→</i>}
            </li>
          ))}
        </ol>
      </section>

      <section className="policy-panel">
        <div>
          <div className="eyebrow">{text("securityPolicy")}</div>
          <h2>{text("safeBoundary")}</h2>
        </div>
        <ul>
          {(["networkNone", "readOnly", "nonRoot", "bounded"] as MessageKey[]).map(
            (policy) => (
              <li key={policy}>
                <span aria-hidden="true">✓</span>
                {text(policy)}
              </li>
            ),
          )}
        </ul>
      </section>
    </div>
  );
}

export default App;
