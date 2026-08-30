import type { Locale, MessageKey } from "./i18n";
import "./LandingPage.css";

const repositoryUrl = "https://github.com/JTech-CO/OpenTCAD";

interface LandingPageProps {
  locale: Locale;
  text: (key: MessageKey) => string;
  onLocaleChange: (locale: Locale) => void;
  onOpenWorkspace: () => void;
}

const capabilityCards: Array<{
  number: string;
  title: MessageKey;
  detail: MessageKey;
  marker: string;
}> = [
  {
    number: "01",
    title: "introProcessTitle",
    detail: "introProcessDetail",
    marker: "PRC",
  },
  {
    number: "02",
    title: "introDeviceTitle",
    detail: "introDeviceDetail",
    marker: "DEV",
  },
  {
    number: "03",
    title: "introCompareTitle",
    detail: "introCompareDetail",
    marker: "I–V",
  },
  {
    number: "04",
    title: "introBoundaryTitle",
    detail: "introBoundaryDetail",
    marker: "SAFE",
  },
];

const workflow: Array<{ number: string; title: MessageKey; detail: MessageKey }> = [
  { number: "01", title: "introFlowDeck", detail: "introFlowDeckDetail" },
  {
    number: "02",
    title: "introFlowStructure",
    detail: "introFlowStructureDetail",
  },
  { number: "03", title: "introFlowDevice", detail: "introFlowDeviceDetail" },
  { number: "04", title: "introFlowReview", detail: "introFlowReviewDetail" },
];

export function LandingPage({
  locale,
  text,
  onLocaleChange,
  onOpenWorkspace,
}: LandingPageProps) {
  return (
    <div className="landing-page" id="top" data-ui="precision-cad">
      <a className="skip-link" href="#landing-main">
        {text("skipToMain")}
      </a>
      <header className="landing-header">
        <a className="landing-brand" href="#top" aria-label="OpenTCAD">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>
            <strong>OpenTCAD</strong>
            <small>{text("appSubtitle")}</small>
          </span>
        </a>

        <nav className="landing-nav" aria-label={text("introNavigation")}>
          <a href="#capabilities">{text("introNavCapabilities")}</a>
          <a href="#workflow">{text("introNavWorkflow")}</a>
          <a href="#scope">{text("introNavScope")}</a>
        </nav>

        <div className="landing-header-actions">
          <a
            className="landing-github-link"
            href={repositoryUrl}
            target="_blank"
            rel="noreferrer"
          >
            GitHub <span aria-hidden="true">↗</span>
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
              onClick={() => onLocaleChange("en")}
            >
              EN
            </button>
            <button
              type="button"
              className={locale === "ko" ? "active" : ""}
              aria-pressed={locale === "ko"}
              onClick={() => onLocaleChange("ko")}
            >
              한국어
            </button>
          </div>
        </div>
      </header>

      <main id="landing-main">
        <section className="landing-hero" aria-labelledby="intro-title">
          <div className="landing-hero-copy">
            <div className="landing-kicker">
              <span aria-hidden="true" />
              {text("introEyebrow")}
            </div>
            <h1 id="intro-title">
              {text("introTitleLead")}
              <span>{text("introTitleAccent")}</span>
            </h1>
            <p className="landing-lede">{text("introDescription")}</p>
            <div className="landing-actions">
              <button
                type="button"
                className="landing-primary"
                onClick={onOpenWorkspace}
              >
                {text("introOpenWorkspace")}
                <span aria-hidden="true">→</span>
              </button>
              <a
                className="landing-secondary"
                href={repositoryUrl}
                target="_blank"
                rel="noreferrer"
              >
                {text("introViewSource")}
                <span aria-hidden="true">↗</span>
              </a>
            </div>
            <div className="landing-status" role="note">
              <span className="mode-beacon" aria-hidden="true" />
              <span>
                <small>{text("introStatus")}</small>
                <strong>{text("introStatusValue")}</strong>
              </span>
            </div>
          </div>

          <div className="landing-hero-art">
            <div className="landing-art-frame">
              <div className="landing-art-bar">
                <span>{text("introVisualLabel")}</span>
                <span>
                  <i aria-hidden="true" />
                  {text("introVisualState")}
                </span>
              </div>
              <img src="./og.png" alt={text("introVisualAlt")} />
              <div className="landing-art-tags" aria-hidden="true">
                <span>SUPREM-IV.GS</span>
                <span>DEVSIM</span>
                <span>OCI</span>
              </div>
            </div>
          </div>

          <dl className="landing-proof">
            <div>
              <dt>01</dt>
              <dd>{text("introProofBilingual")}</dd>
            </div>
            <div>
              <dt>02</dt>
              <dd>{text("introProofPortable")}</dd>
            </div>
            <div>
              <dt>03</dt>
              <dd>{text("introProofSafe")}</dd>
            </div>
          </dl>
        </section>

        <section className="landing-section" id="capabilities">
          <div className="landing-section-heading">
            <div>
              <div className="landing-kicker">{text("introCapabilitiesEyebrow")}</div>
              <h2>{text("introCapabilitiesTitle")}</h2>
            </div>
            <p>{text("introCapabilitiesDescription")}</p>
          </div>
          <div className="landing-capability-grid">
            {capabilityCards.map((card) => (
              <article className="landing-capability-card" key={card.number}>
                <div>
                  <span>{card.number}</span>
                  <i aria-hidden="true">{card.marker}</i>
                </div>
                <h3>{text(card.title)}</h3>
                <p>{text(card.detail)}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="landing-workflow" id="workflow">
          <div className="landing-workflow-copy">
            <div className="landing-kicker">{text("introWorkflowEyebrow")}</div>
            <h2>{text("introWorkflowTitle")}</h2>
            <p>{text("introWorkflowDescription")}</p>
            <button
              type="button"
              className="landing-text-button"
              onClick={onOpenWorkspace}
            >
              {text("introOpenWorkspace")} <span aria-hidden="true">→</span>
            </button>
          </div>
          <ol className="landing-flow-list">
            {workflow.map((step) => (
              <li key={step.number}>
                <span>{step.number}</span>
                <div>
                  <h3>{text(step.title)}</h3>
                  <p>{text(step.detail)}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="landing-scope" id="scope">
          <div className="landing-scope-heading">
            <div className="landing-kicker">{text("introScopeEyebrow")}</div>
            <h2>{text("introScopeTitle")}</h2>
          </div>
          <div className="landing-scope-grid">
            <article className="available">
              <span>{text("introAvailableLabel")}</span>
              <h3>{text("introAvailableTitle")}</h3>
              <p>{text("introAvailableDetail")}</p>
            </article>
            <article className="restricted">
              <span>{text("introUnavailableLabel")}</span>
              <h3>{text("introUnavailableTitle")}</h3>
              <p>{text("introUnavailableDetail")}</p>
            </article>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div>
          <strong>OpenTCAD</strong>
          <p>{text("introFooter")}</p>
        </div>
        <div>
          <a href="https://github.com/JTech-CO/OpenTCAD/blob/main/LICENSE">MIT</a>
          <a href={`${repositoryUrl}/blob/main/docs/${locale}/architecture.md`}>
            {text("readArchitecture")}
          </a>
          <span>© 2026 JTech-CO</span>
        </div>
      </footer>
    </div>
  );
}
