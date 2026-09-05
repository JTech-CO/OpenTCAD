import { useEffect, useRef, useState } from "react";
import { downloadWorkspaceJson, parseWorkspaceJson, readWorkspaceFile } from "../m4/files";
import { NumericPlot } from "./Calculator";
import { mvpEn, mvpKo } from "./copy";
import { decodeJob, defaultPn, labRequest, PN_MODEL, pnLimits, validatePn, type LabJob, type PnInput } from "./solver-client";

export function SolverPanel({ locale, token }: { locale: "en" | "ko"; token: string | null }) {
  const ko = locale === "ko", t = ko ? mvpKo : mvpEn;
  const [input, setInput] = useState<PnInput>(defaultPn), [job, setJob] = useState<LabJob | null>(null);
  const [pending, setPending] = useState<PnInput | null>(null), [error, setError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const active = useRef<string | null>(null);
  const running = submitting || job?.state === "running";
  let valid = true; try { validatePn(input); } catch { valid = false; }
  const labels: Record<keyof typeof pnLimits, string> = ko ? {
    lengthUm: "접합 전체 길이 (μm)", acceptorsCm3: "p영역 억셉터 (cm⁻³)", donorsCm3: "n영역 도너 (cm⁻³)", areaUm2: "단면적 (μm²)", voltageV: "최종 순방향 전압 (V)",
  } : { lengthUm: "Total junction length (μm)", acceptorsCm3: "p-region acceptors (cm⁻³)", donorsCm3: "n-region donors (cm⁻³)", areaUm2: "Cross-sectional area (μm²)", voltageV: "Final forward voltage (V)" };
  const change = (next: PnInput) => { setInput(next); setJob(null); setError(false); };
  useEffect(() => {
    if (!token || job?.state !== "running") return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try { const result = decodeJob(await labRequest(token, `/v1/lab/jobs/${job.requestId}`, undefined, controller.signal), job.requestId); setJob(result); }
      catch (failure) { if (!controller.signal.aborted) { setError(true); if (failure instanceof Error && failure.message === "HTTP 404") setJob(current => current ? { ...current, state: "failed" } : null); } }
    }, 500);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [token, job]);
  useEffect(() => () => {
    if (active.current && token) void labRequest(token, `/v1/lab/jobs/${active.current}/cancel`, {}).catch(() => {});
  }, [token]);
  const run = async () => {
    if (!token || !valid || running) return;
    const id = crypto.randomUUID(); active.current = id; setSubmitting(true); setError(false); setJob(null);
    try { setJob(decodeJob(await labRequest(token, "/v1/lab/jobs", { requestId: id, input }), id)); }
    catch (failure) { setError(true); if (!(failure instanceof Error && failure.message.startsWith("HTTP "))) setJob({requestId: id, inputSha256: "", state: "running"}); }
    finally { setSubmitting(false); }
  };
  const result = job?.state === "complete" ? job.result : null;
  return <section className="lab-solver" aria-label={t.solver}><h2>{t.solver}</h2><p>{t.localHelp}</p>
    <p>{ko ? "1D 실리콘 PN 접합 · Poisson 및 전자·정공 연속 방정식 · 300 K" : "1D silicon PN junction · Poisson and electron/hole continuity equations · 300 K"}</p>
    {!token && <p>{t.unavailable} <code>npm run local:lab</code></p>}
    <div className="lab-inputs">{(Object.keys(pnLimits) as (keyof typeof pnLimits)[]).map(key => <label key={key}>{labels[key]}
      <input type="number" step="any" disabled={running} min={pnLimits[key][0]} max={pnLimits[key][1]} value={Number.isFinite(input[key]) ? input[key] : ""} onChange={e => change({ ...input, [key]: e.target.valueAsNumber })} />
      <small>{pnLimits[key][0]} ~ {pnLimits[key][1]}</small></label>)}
      <label>{ko ? "메시 구간 수" : "Mesh intervals"}<select disabled={running} value={input.intervals} onChange={e => change({ ...input, intervals: Number(e.target.value) })}>{[100,200,400].map(v => <option key={v}>{v}</option>)}</select></label>
    </div>
    {!valid && <p role="alert">{t.invalid}</p>}
    <div className="m4-toolbar"><button className="primary-button" disabled={!token || running || !valid} onClick={run}>{ko ? "DEVSIM 해석 실행" : "Run DEVSIM solve"}</button>
      <button className="quiet-button" disabled={!token || job?.state !== "running" || !active.current} onClick={async () => {
        try { const id = active.current!; setJob(decodeJob(await labRequest(token!, `/v1/lab/jobs/${id}/cancel`, {}), id)); setError(false); }
        catch { setError(true); }
      }}>{ko ? "해석 취소" : "Cancel solve"}</button></div>
    <p role="status">{submitting ? (ko ? "제출 중" : "Submitting") : job ? ({ running: ko ? "실제 솔버 계산 중" : "Solving with DEVSIM", complete: ko ? "해석 완료" : "Solve complete", cancelled: ko ? "취소됨" : "Cancelled", failed: ko ? "해석 실패, 결과 없음" : "Solve failed; no result" })[job.state] : ""}</p>
    {error && <div role="alert"><p>{ko ? "요청 실패: 서버 연결, 입력, 수렴 상태를 확인하세요. 통신 실패만으로 실행 취소를 보장하지 않으므로 취소 버튼을 사용하세요." : "Request failed: check the service, input and convergence. A transport failure does not guarantee cancellation; use Cancel solve."}</p>{job?.state === "running" && <button className="quiet-button" onClick={() => {setError(false);setJob({...job});}}>{ko ? "상태 다시 확인" : "Recheck status"}</button>}</div>}
    {result && <>
      <p>{ko ? "실제 DEVSIM 결과, 제품 자격 미승인" : "Computed by DEVSIM; not product-qualified"} · {result.solverVersion}</p>
      <figure className="lab-device"><figcaption>{ko ? "계산 전위의 1D 공간 지도 (2D 해석 아님)" : "Computed 1D potential map (not a 2D solve)"}</figcaption>
        <svg viewBox="0 0 640 140" role="img" aria-label={ko ? "계산 전위 공간 지도" : "Computed potential map"}>
          {result.xUm.slice(0,-1).map((x,i) => {const lo = Math.min(...result.potentialV), hi = Math.max(...result.potentialV); const fraction = (result.potentialV[i]-lo)/(hi-lo||1); return <rect key={x} x={20+600*x/result.input.lengthUm} y="38" width={600*(result.xUm[i+1]-x)/result.input.lengthUm+.1} height="60" fill={`hsl(${220-190*fraction} 65% 55%)`}><title>{x} μm: {result.potentialV[i]} V</title></rect>;})}
          <text x="20" y="25">p · A</text><text x="620" y="25" textAnchor="end">n · K</text><path d="M320 30 V103" stroke="white" strokeDasharray="4 3" />
          <text x="20" y="124">0 μm</text><text x="620" y="124" textAnchor="end">{result.input.lengthUm} μm</text>
        </svg><p>{Math.min(...result.potentialV).toPrecision(4)} V ({ko ? "파랑" : "blue"}) → {Math.max(...result.potentialV).toPrecision(4)} V ({ko ? "주황" : "orange"})</p>
      </figure>
      <div className="lab-curves"><NumericPlot points={result.iv.map(([v,i]) => [v,i*1e9])} title="I–V" xLabel="V (anode)" yLabel="I (nA)" />
        <NumericPlot points={result.xUm.map((x,i) => [x,result.potentialV[i]])} title={ko ? "최종 바이어스 전위" : "Potential at final bias"} xLabel="x (μm)" yLabel="ψ (V)" />
        <NumericPlot points={result.xUm.map((x,i) => [x,Math.log10(result.electronsCm3[i])])} title={ko ? "전자 농도" : "Electron density"} xLabel="x (μm)" yLabel="log₁₀(n / cm⁻³)" />
        <NumericPlot points={result.xUm.map((x,i) => [x,Math.log10(result.holesCm3[i])])} title={ko ? "정공 농도" : "Hole density"} xLabel="x (μm)" yLabel="log₁₀(p / cm⁻³)" /></div>
      <details><summary>{ko ? "입력·솔버·재현 정보" : "Inputs, solver and reproducibility"}</summary><pre className="lab-provenance">{JSON.stringify({ input: result.input, checks: result.checks, environment: result.environment, inputSha256: result.inputSha256, templateSha256: result.templateSha256, resultSha256: result.resultSha256 }, null, 2)}</pre></details>
      <details><summary>{t.samples}</summary><div className="sample-table"><table><thead><tr><th>x (μm)</th><th>ψ (V)</th><th>n (cm⁻³)</th><th>p (cm⁻³)</th></tr></thead><tbody>{result.xUm.map((x,i) => <tr key={x}><td>{x}</td><td>{result.potentialV[i]}</td><td>{result.electronsCm3[i]}</td><td>{result.holesCm3[i]}</td></tr>)}</tbody></table></div></details>
      <button className="quiet-button" onClick={() => { try {downloadWorkspaceJson(JSON.stringify(result, null, 2), "opentcad-pn-result.json");} catch {setError(true);} }}>{t.save}</button>
    </>}
    <label className="file-field">{t.open}<input type="file" accept=".json" disabled={running} onChange={async e => {
      const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; setPending(null);
      try { const record = parseWorkspaceJson(await readWorkspaceFile(file)) as Record<string, unknown>;
        if (record.format !== "opentcad-solver-result" || record.schemaVersion !== 1 || record.model !== PN_MODEL) throw new Error("format");
        setPending(validatePn(record.input));
      } catch { setError(true); }
    }} /></label>
    {pending && <div className="import-review"><p>{t.replace}</p><pre>{JSON.stringify(pending,null,2)}</pre><button className="quiet-button" disabled={running} onClick={() => {change(pending);setPending(null);}}>{t.apply}</button><button className="quiet-button" onClick={() => setPending(null)}>{t.discard}</button></div>}
    <p className="lab-warning">{ko ? "이상적인 옴 접촉, 균일한 두 도핑 영역, 고정 이동도·수명·진성 농도를 가정합니다. 공정 해석, 2D MOSFET, 온도 스윕, 항복 모델은 아닙니다. 수렴 실패 시 결과를 생성하지 않습니다. 세션당 최대 32회 실행이며 새로고침 전에 결과를 저장하세요." : "Assumes ideal ohmic contacts, two uniform doping regions, constant mobility, lifetime and intrinsic density. Not process simulation, a 2D MOSFET, a temperature sweep or a breakdown model. Failed solves produce no result. Up to 32 jobs per session; save results before reloading."}</p>
  </section>;
}
