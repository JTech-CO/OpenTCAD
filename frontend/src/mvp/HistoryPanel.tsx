import { useEffect, useRef, useState } from "react";
import { downloadWorkspaceJson, exactRecord } from "../m4/files";
import { NumericPlot } from "./Calculator";
import { MosMap } from "./MosPanel";
import { decodeMosResult, type MosResult } from "./mos-client";
import { decodeSolverResult, labRequest, PN_MODEL, type SolverResult } from "./solver-client";

type Result = SolverResult | MosResult;
interface Summary { requestId: string; state: "running" | "complete" | "failed" | "cancelled"; inputSha256: string; error?: string }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
export function decodeHistory(value: unknown): Summary[] {
  const data = exactRecord(value, ["jobs"]);
  if (!Array.isArray(data.jobs) || data.jobs.length > 32) throw new Error("history-limit");
  const jobs = data.jobs.map(value => {
    const row = exactRecord(value, ["requestId", "state", "inputSha256", ...(value && typeof value === "object" && "error" in value ? ["error"] : [])]);
    if (typeof row.requestId !== "string" || !uuid.test(row.requestId) || !["running","complete","failed","cancelled"].includes(row.state as string) || typeof row.inputSha256 !== "string" || !/^[a-f0-9]{64}$/u.test(row.inputSha256)) throw new Error("history-row");
    if ("error" in row && (row.state !== "failed" || !["solver-failed","interrupted","history-write-failed"].includes(row.error as string))) throw new Error("history-error");
    return row as unknown as Summary;
  });
  if (new Set(jobs.map(row => row.requestId)).size !== jobs.length) throw new Error("history-duplicate");
  return jobs;
}
export function decodeStored(value: unknown, summary: Summary): Result {
  const row = exactRecord(value, ["requestId","inputSha256","state","result"]);
  if (row.requestId !== summary.requestId || row.inputSha256 !== summary.inputSha256 || row.state !== "complete") throw new Error("history-identity");
  const result = (row.result as {model?:unknown} | null)?.model === PN_MODEL ? decodeSolverResult(row.result) : decodeMosResult(row.result);
  if (result.inputSha256 !== summary.inputSha256) throw new Error("history-input");
  return result;
}
export function comparable(a: Result, b: Result): boolean {
  return a.model === b.model && a.solverVersion === b.solverVersion && a.templateSha256 === b.templateSha256 &&
    (a.model === PN_MODEL || b.model === PN_MODEL || JSON.stringify(a.dopingSource) === JSON.stringify(b.dopingSource));
}

export function HistoryPanel({locale,token}: {locale:"en"|"ko";token:string|null}) {
  const ko = locale === "ko";
  const [rows,setRows] = useState<Summary[]>([]), [selected,setSelected] = useState<Result|null>(null), [baseline,setBaseline] = useState<Result|null>(null);
  const [busy,setBusy] = useState(false), [error,setError] = useState(false), [loaded,setLoaded] = useState(false);
  const request = useRef<AbortController|null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const start = () => { request.current?.abort(); const controller = new AbortController(); request.current = controller; setBusy(true); setError(false); return controller; };
  const refresh = async () => {
    if (!token) return;
    const controller = start();
    try { const jobs = decodeHistory(await labRequest(token,"/v1/lab/jobs",undefined,controller.signal)); if (!controller.signal.aborted) {setRows(jobs);setLoaded(true);} }
    catch { if (!controller.signal.aborted) setError(true); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  };
  const open = async (summary: Summary) => {
    if (!token) return;
    const controller = start(); setSelected(null);
    try { const result = decodeStored(await labRequest(token,`/v1/lab/jobs/${summary.requestId}`,undefined,controller.signal),summary); if (!controller.signal.aborted) setSelected(result); }
    catch { if (!controller.signal.aborted) setError(true); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  };
  const states = ko ? {running:"계산 중",complete:"완료",failed:"실패",cancelled:"취소됨"} : {running:"Running",complete:"Complete",failed:"Failed",cancelled:"Cancelled"};
  return <section className="lab-solver" aria-label={ko ? "실행 이력" : "Run history"}>
    <h2>{ko ? "실행 이력과 결과 비교" : "Run history and comparison"}</h2>
    <p>{ko ? "저장된 실제 결과를 다시 열어 확인합니다. 새 계산을 실행하거나 편집 중인 입력을 덮어쓰지 않습니다. Windows MVP는 재시작 후에도 이력을 보존하고 일반 실험용 서비스는 세션 이력만 제공합니다." : "Reopen computed results without running a solve or replacing editor inputs. Windows MVP retains history across restarts; the ordinary experimental service retains only session history."}</p>
    {!token && <p>{ko ? "로컬 서비스의 개인용 주소로 접속하면 이력을 조회할 수 있습니다. 정적 페이지는 서버에 연결하지 않습니다." : "Open the private local-service URL to retrieve history. The static page does not connect to a server."}</p>}
    <button className="quiet-button" disabled={!token || busy} onClick={refresh}>{ko ? "이력 새로고침" : "Refresh history"}</button>
    <p role="status">{busy ? (ko ? "불러오는 중" : "Loading") : loaded ? `${rows.length} / 32` : ""}</p>
    {error && <p role="alert">{ko ? "이력을 확인하지 못했습니다. 연결과 결과 형식을 확인하세요. 저장된 결과는 변경하지 않았습니다." : "Could not verify history. Check the connection and result format. Saved results were not changed."}</p>}
    {loaded && !rows.length && <p>{ko ? "아직 실행 이력이 없습니다." : "No retained runs yet."}</p>}
    {!!rows.length && <div className="sample-table"><table><thead><tr><th>{ko ? "작업 ID" : "Job ID"}</th><th>{ko ? "상태" : "State"}</th><th>{ko ? "결과" : "Result"}</th></tr></thead><tbody>{rows.map(row => <tr key={row.requestId}><td><code>{row.requestId}</code></td><td>{states[row.state]}{row.error === "interrupted" ? (ko ? " (재시작 시 중단 확인)" : " (interrupted on restart)") : ""}</td><td><button className="quiet-button" disabled={busy || row.state !== "complete"} onClick={() => open(row)}>{ko ? "결과 열기" : "Open result"}</button></td></tr>)}</tbody></table></div>}
    {selected && <div className="history-result"><h3>{selected.model === PN_MODEL ? "PN · 1D" : "MOSFET · 2D"}</h3>
      <p>{ko ? "저장된 실제 솔버 결과, 새 실행 아님" : "Stored solver result, not a new execution"} · DEVSIM {selected.solverVersion}</p>
      {selected.model !== PN_MODEL && <MosMap result={selected} ko={ko} />}
      <NumericPlot points={selected.iv} title={ko ? "저장된 I-V" : "Stored I-V"} xLabel="V" yLabel="I (A)" />
      {selected.model === PN_MODEL && <NumericPlot points={selected.xUm.map((x,i) => [x,selected.potentialV[i]])} title={ko ? "저장된 전위" : "Stored potential"} xLabel="x (μm)" yLabel="ψ (V)" />}
      <div className="m4-toolbar"><button className="quiet-button" onClick={() => setBaseline(selected)}>{ko ? "비교 기준으로 지정" : "Set comparison baseline"}</button><button className="quiet-button" onClick={() => {try {downloadWorkspaceJson(JSON.stringify(selected,null,2),selected.model === PN_MODEL ? "opentcad-pn-result.json" : "opentcad-mos-result.json");} catch {setError(true);} }}>{ko ? "결과 내보내기" : "Export result"}</button></div>
      {baseline && <div><button className="quiet-button" onClick={() => setBaseline(null)}>{ko ? "비교 기준 해제" : "Clear baseline"}</button>{comparable(baseline,selected) ? <><p>{ko ? "각 입력의 마지막 바이어스 점 전류 비교입니다. 같은 바이어스나 수치 검증 통과를 의미하지 않습니다." : "Compare final-bias currents for each input. This does not imply equal bias or numerical validation."}</p><dl className="lab-metrics"><div><dt>{ko ? "기준 전압 / 전류" : "Baseline voltage / current"}</dt><dd>{baseline.iv.at(-1)![0]} V / {baseline.iv.at(-1)![1].toExponential(6)} A</dd></div><div><dt>{ko ? "선택 전압 / 전류" : "Selected voltage / current"}</dt><dd>{selected.iv.at(-1)![0]} V / {selected.iv.at(-1)![1].toExponential(6)} A</dd></div><div><dt>ΔI</dt><dd>{(selected.iv.at(-1)![1]-baseline.iv.at(-1)![1]).toExponential(6)} A</dd></div></dl></> : <p role="alert">{ko ? "모델, 솔버, 소스 지문 또는 공정 출처가 달라 직접 비교하지 않습니다." : "Model, solver, source fingerprint or process provenance differs; direct comparison is disabled."}</p>}</div>}
      <details><summary>{ko ? "입력과 출처" : "Inputs and provenance"}</summary><pre className="lab-provenance">{JSON.stringify({input:selected.input,environment:selected.environment,checks:selected.checks,templateSha256:selected.templateSha256,resultSha256:selected.resultSha256},null,2)}</pre></details>
    </div>}
  </section>;
}
