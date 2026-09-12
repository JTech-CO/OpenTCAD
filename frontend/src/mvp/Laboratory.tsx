import type { Locale } from "../i18n";
import { Calculator } from "./Calculator";
import { mvpEn, mvpKo } from "./copy";
import { SolverPanel } from "./SolverPanel";
import { MosPanel } from "./MosPanel";
import { HistoryPanel } from "./HistoryPanel";

export function Laboratory({ locale, onLocaleChange, onWorkspace, onOverview, experimentToken }: {
  locale: Locale; onLocaleChange: (value: Locale) => void; onWorkspace: () => void; onOverview: () => void;
  experimentToken: string | null;
}) {
  const t = locale === "ko" ? mvpKo : mvpEn;
  return <main className="laboratory"><nav className="lab-topbar" aria-label="OpenTCAD">
    <strong>OpenTCAD</strong><div className="m4-toolbar">
      <button className="quiet-button" onClick={onOverview}>{locale === "ko" ? "소개" : "Overview"}</button>
      <button className="quiet-button" onClick={onWorkspace}>{locale === "ko" ? "참조 작업공간" : "Reference workspace"}</button>
      <button className="quiet-button" onClick={() => onLocaleChange("en")} aria-pressed={locale === "en"}>EN</button>
      <button className="quiet-button" onClick={() => onLocaleChange("ko")} aria-pressed={locale === "ko"}>한국어</button>
    </div></nav><header className="lab-heading"><div><h1>{t.title}</h1><p>{t.subtitle}</p></div></header>
    <nav className="lab-workflow m4-toolbar" aria-label={locale === "ko" ? "실험실 작업 이동" : "Laboratory workflow"}>
      {[["lab-calculator",locale === "ko" ? "즉시 계산" : "Calculator"],["lab-mos","2D MOSFET"],["lab-pn","PN"],["lab-history",locale === "ko" ? "이력·비교" : "History / compare"]].map(([id,label]) => <button className="quiet-button" key={id} onClick={() => document.getElementById(id)?.scrollIntoView({block:"start"})}>{label}</button>)}
    </nav>
    <div id="lab-calculator"><Calculator locale={locale} /></div>
    <div id="lab-mos"><MosPanel locale={locale} token={experimentToken} /></div>
    <div id="lab-pn"><SolverPanel locale={locale} token={experimentToken} /></div>
    <div id="lab-history"><HistoryPanel key={experimentToken ?? "static"} locale={locale} token={experimentToken} /></div>
  </main>;
}
