import { useState } from "react";
import { downloadWorkspaceJson, readWorkspaceFile } from "../m4/files";
import { defaultMos, MODEL, mosCurves, mosPoint, mosRecord, parameters, parseMosRecord, validateMos, type MosInput, type Parameter, type Point } from "./models";
import { mvpEn, mvpKo } from "./copy";
import "./laboratory.css";

export function NumericPlot({ points, title, xLabel, yLabel }: { points: Point[]; title: string; xLabel: string; yLabel: string }) {
  const xmin = Math.min(...points.map(p => p[0])), xmax = Math.max(...points.map(p => p[0]));
  let ymin = Math.min(0, ...points.map(p => p[1])), ymax = Math.max(...points.map(p => p[1]));
  if (ymin === ymax) { ymin -= 0.5; ymax += 0.5; }
  return <figure className="lab-plot"><figcaption>{title}</figcaption><svg viewBox="0 0 640 320" role="img" aria-label={title}>
    {[0, 1, 2, 3, 4].map(i => <g key={i}><path d={`M105 ${260-i*55} H610 M${105+i*126.25} 40 V260`} className="lab-grid" />
      <text x="95" y={266-i*55} textAnchor="end">{(ymin+(ymax-ymin)*i/4).toPrecision(3)}</text>
      <text x={105+i*126.25} y="285" textAnchor="middle">{(xmin+(xmax-xmin)*i/4).toPrecision(3)}</text></g>)}
    <text x="105" y="23">{yLabel}</text><text x="610" y="313" textAnchor="end">{xLabel}</text>
    <polyline fill="none" stroke="#68e7dc" strokeWidth="3" points={points.map(([x,y]) => `${105+(x-xmin)/(xmax-xmin||1)*505},${260-(y-ymin)/(ymax-ymin)*220}`).join(" ")} />
  </svg></figure>;
}
export function Calculator({ locale }: { locale: "en" | "ko" }) {
  const t = locale === "ko" ? mvpKo : mvpEn;
  const [input, setInput] = useState<MosInput>(defaultMos);
  const [pending, setPending] = useState<MosInput | null>(null);
  const [notice, setNotice] = useState("");
  let valid = true; try { validateMos(input); } catch { valid = false; }
  const point = valid ? mosPoint(input) : null, curves = valid ? mosCurves(input) : null;
  return <section className="lab-calculator" aria-label={t.calculator}>
    <header><h2>{t.calculator}</h2><p>{t.model}</p></header>
    <div className="lab-layout"><div className="lab-inputs">
      {(Object.keys(parameters) as Parameter[]).map(key => <label key={key}>{t[key]}
        <input type="number" min={parameters[key][0]} max={parameters[key][1]} step="any" value={Number.isFinite(input[key]) ? input[key] : ""}
          onChange={e => { setInput({ ...input, [key]: e.target.valueAsNumber }); setNotice(""); }} />
        <small>{parameters[key][0]} ~ {parameters[key][1]}</small>
      </label>)}
    </div><div className="lab-results">
      {!valid && <p role="alert">{t.invalid}</p>}
      {point && curves && <>
        <dl className="lab-metrics" aria-live="polite"><div><dt>{t.threshold}</dt><dd>{point.thresholdV.toFixed(4)} V</dd></div>
          <div><dt>{t.current}</dt><dd data-testid="calculated-current">{(point.currentA*1e3).toPrecision(5)} mA</dd></div>
          <div><dt>gm</dt><dd>{(point.gmS*1e3).toPrecision(4)} mS</dd></div><div><dt>{MODEL}</dt><dd>{t[point.region]}</dd></div></dl>
        <div className="lab-curves"><NumericPlot points={curves.output} title={`${t.output} · VGS = ${input.gateV} V`} xLabel="VDS (V)" yLabel="ID (mA)" />
          <NumericPlot points={curves.transfer} title={`${t.transfer} · VDS = ${input.drainV} V`} xLabel="VGS (V)" yLabel="ID (mA)" /></div>
        <figure className="lab-device"><figcaption>{t.drawing}</figcaption><svg viewBox="0 0 640 200" role="img" aria-label={t.drawing}>
          <rect x="20" y="90" width="600" height="85" fill="#b9d9ec" />
          <rect x="20" y="90" width={600/(input.lengthUm+2)} height="25" fill="#386cb0" /><rect x={620-600/(input.lengthUm+2)} y="90" width={600/(input.lengthUm+2)} height="25" fill="#386cb0" />
          <rect x={20+600/(input.lengthUm+2)} y={90-input.oxideNm*0.35} width={600*input.lengthUm/(input.lengthUm+2)} height={input.oxideNm*0.35} fill="#e2cf89" />
          <rect x={20+600/(input.lengthUm+2)} y={65-input.oxideNm*0.35} width={600*input.lengthUm/(input.lengthUm+2)} height="25" fill="#d9a23e" />
          <text x="30" y="80">S</text><text x="610" y="80" textAnchor="end">D</text>
          <text x="320" y="20" textAnchor="middle">G · L={input.lengthUm} μm · W={input.widthUm} μm</text>
          <text x="320" y="145" textAnchor="middle" style={{fill: "#132c40"}}>p-Si · NA={input.dopingCm3.toExponential(2)} cm⁻³</text>
        </svg><p>{t.schematic}</p></figure>
        <details><summary>{t.samples}</summary><div className="sample-table"><table><thead><tr><th>{t.voltage}</th><th>{t.output} (mA)</th><th>{t.transfer} (mA)</th></tr></thead>
          <tbody>{curves.output.map(([x,y],i) => <tr key={x}><td>{x}</td><td>{y}</td><td>{curves.transfer[i][1]}</td></tr>)}</tbody></table></div></details>
      </>}
    </div></div>
    <p className="lab-warning">{t.limits}</p>
    <div className="m4-toolbar"><button className="quiet-button" disabled={!valid} onClick={() => {
      try { downloadWorkspaceJson(JSON.stringify(mosRecord(input), null, 2), "opentcad-nmos-calculation.json"); } catch { setNotice(t.fileError); }
    }}>{t.save}</button><label className="file-field">{t.open}<input type="file" accept=".json" onChange={async e => {
      const file = e.target.files?.[0]; e.target.value = ""; if (!file) return;
      setPending(null); try { setPending(parseMosRecord(await readWorkspaceFile(file))); } catch { setNotice(t.fileError); }
    }} /></label></div>
    {pending && <div className="import-review"><p>{t.replace}</p><pre>{JSON.stringify(pending, null, 2)}</pre><button className="quiet-button" onClick={() => {setInput(pending);setPending(null);setNotice(t.restored);}}>{t.apply}</button><button className="quiet-button" onClick={() => setPending(null)}>{t.discard}</button></div>}
    <p role="status">{notice}</p><p>{t.fileHelp}</p>
  </section>;
}
