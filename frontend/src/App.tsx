import { useEffect, useMemo, useState } from "react";
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
import {
  DeviceCanvas,
  IvCanvas,
  ProfileCanvas,
} from "./components/ScientificCanvas";
import { LandingPage } from "./LandingPage";

const repositoryUrl = "https://github.com/JTech-CO/OpenTCAD";
type AppSurface = "intro" | "workspace";

function getInitialSurface(): AppSurface {
  return window.location.hash === "#workspace" ? "workspace" : "intro";
}

function App() {
  const [locale, setLocale] = useState<Locale>(getInitialLocale);
  const [surface, setSurface] = useState<AppSurface>(getInitialSurface);
  const [view, setView] = useState<WorkspaceView>("process");
  const [deck, setDeck] = useState(DEMO_DECK);
  const [selectedField, setSelectedField] =
    useState<ProfileField>("netActive");
  const [runState, setRunState] = useState<RunState>("idle");
  const [activeStep, setActiveStep] = useState(0);
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
      if (activeStep >= workflowSteps.length - 1) {
        setRunState("complete");
      } else {
        setActiveStep((step) => step + 1);
      }
    }, 620);

    return () => window.clearTimeout(timer);
  }, [activeStep, runState, surface]);

  const lineCount = useMemo(
    () => deck.split(/\r?\n/).filter((line) => line.length > 0).length,
    [deck],
  );

  const progress =
    runState === "idle"
      ? 0
      : runState === "complete"
        ? 100
        : Math.round(((activeStep + 1) / workflowSteps.length) * 100);

  const startReferenceRun = () => {
    setActiveStep(0);
    setRunState("running");
  };

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
    <div className="app-shell">
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
            <strong>{text("staticPreview")}</strong>
            <span>{text("staticModeDetail")}</span>
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
          <div className="project-title">{text("sampleProject")}</div>
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
                ?
              </span>
            </button>
          ))}
        </nav>

        <section className="workflow-card" aria-labelledby="workflow-heading">
          <div className="section-label" id="workflow-heading">
            {text("workflow")}
          </div>
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
        </section>

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

      <main className="main-workspace">
        <div className="safety-banner" role="note">
          <div className="safety-shield" aria-hidden="true">
            <span />
          </div>
          <div>
            <strong>{text("safeBoundary")}</strong>
            <p>{text("safeBoundaryDetail")}</p>
          </div>
          <span className="static-stamp">{text("staticLabel")}</span>
        </div>

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
                <strong>{text("referenceOnly")}</strong>
                <small>{text("notSolverOutput")}</small>
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
          />
        )}

        {view === "device" && <DeviceView text={text} />}

        {view === "compare" && <CompareView text={text} />}

        {view === "runtime" && <RuntimeView locale={locale} text={text} />}
      </main>

      <aside className="inspector" aria-label={text("runDetails")}>
        <section className="inspector-section">
          <div className="section-label">{text("runDetails")}</div>
          <div className="run-state" aria-live="polite" role="status">
            <span className={`run-state-dot ${runState}`} aria-hidden="true" />
            <div>
              <strong>{text(runState)}</strong>
              <span>ref-ui-0001</span>
            </div>
          </div>
          <div className="progress-track" aria-hidden="true">
            <span style={{ width: `${progress}%` }} />
          </div>
          <dl className="detail-list">
            <div>
              <dt>{text("mode")}</dt>
              <dd>{text("staticPreview")}</dd>
            </div>
            <div>
              <dt>{text("engine")}</dt>
              <dd className="muted-value">{text("disconnected")}</dd>
            </div>
            <div>
              <dt>{text("job")}</dt>
              <dd>{text("referenceOnly")}</dd>
            </div>
          </dl>
          <p className="inspector-help">{text("engineUnavailable")}</p>
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
              <dd>{text("referenceDataset")}</dd>
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
      </aside>
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
}: ProcessViewProps) {
  return (
    <>
      <div className="process-grid">
        <section className="panel editor-panel">
          <div className="panel-header">
            <div>
              <h2>{text("illustrativeDeck")}</h2>
              <p>{text("deckDescription")}</p>
            </div>
            <button type="button" className="quiet-button" onClick={onReset}>
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
          disabled={runState === "running"}
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
    </>
  );
}

function DeviceView({ text }: SharedTextProps) {
  const materials: Array<[MessageKey, string]> = [
    ["silicon", "#16475a"],
    ["oxide", "#86a9ae"],
    ["polysilicon", "#d79b43"],
    ["contact", "#e4edef"],
  ];
  const electrodes: MessageKey[] = ["source", "gate", "drain", "substrate"];

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
        <div className="canvas-frame">
          <DeviceCanvas ariaLabel={text("deviceAria")} />
        </div>
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
            {electrodes.map((electrode, index) => (
              <div key={electrode}>
                <span className="electrode-index">{String(index + 1).padStart(2, "0")}</span>
                <strong>{text(electrode)}</strong>
                <span className="contact-state">{text("contact")}</span>
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
          <dl className="bias-grid">
            <div>
              <dt>{text("gateVoltage")}</dt>
              <dd>0.80 V</dd>
            </div>
            <div>
              <dt>{text("drainVoltage")}</dt>
              <dd>1.00 V</dd>
            </div>
            <div>
              <dt>{text("temperature")}</dt>
              <dd>300 K</dd>
            </div>
          </dl>
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
}

function RuntimeView({ locale, text }: RuntimeViewProps) {
  const path: MessageKey[] = ["browser", "api", "worker", "broker", "ociRuntime"];
  const architectureUrl = `${repositoryUrl}/blob/main/docs/${locale}/architecture.md`;

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
        <section className="mode-card planned">
          <span className="mode-number">02</span>
          <div>
            <div className="mode-card-heading">
              <h2>{text("localEngine")}</h2>
              <span>{text("notAvailableYet")}</span>
            </div>
            <p>{text("localEngineDetail")}</p>
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
