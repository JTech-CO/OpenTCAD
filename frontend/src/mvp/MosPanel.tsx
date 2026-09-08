import { useEffect, useRef, useState } from "react";
import { downloadWorkspaceJson, parseWorkspaceJson, readWorkspaceFile } from "../m4/files";
import { NumericPlot } from "./Calculator";
import { decodeMosJob, defaultMos, mosLimits, validateMos, MOS_MODEL, type MosInput, type MosJob, type MosResult } from "./mos-client";
import { labRequest } from "./solver-client";

export function MosMap({result,ko}:{result:MosResult;ko:boolean}) {
  const [field,setField]=useState("potentialV"),[mesh,setMesh]=useState(false);
  const si=result.regions.silicon;
  const values=field==="potentialV"?si.potentialV:field==="electronsCm3"?si.electronsCm3!.map(v=>Math.log10(v)):si.netDopingCm3!.map(v=>Math.sign(v)*Math.log10(1+Math.abs(v)));
  const lo=Math.min(...values),hi=Math.max(...values),length=result.input.gateLengthUm+1;
  const allX=[...si.xUm,...result.regions.oxide.xUm],allY=[...si.yUm,...result.regions.oxide.yUm];
  const xmin=Math.min(...allX),xmax=Math.max(...allX),ymin=Math.min(...allY),ymax=Math.max(...allY);
  const x=(v:number)=>60+800*(v-xmin)/(xmax-xmin||1), y=(v:number)=>80+325*(v-ymin)/(ymax-ymin||1);
  const contacts=result.contactSegmentsUm ?? {source:[[[0,0],[.4,0]]],drain:[[[length-.4,0],[length,0]]],gate:[[[.5,-result.input.oxideNm*.001],[length-.5,-result.input.oxideNm*.001]]],body:[[[0,.5],[length,.5]]]};
  return <figure className="lab-device mos-map"><figcaption>{ko?"실제 2D 메시 결과":"Computed 2D mesh"}</figcaption>
    <div className="m4-toolbar"><label>{ko?"표시 물리량":"Displayed field"}<select value={field} onChange={e=>setField(e.target.value)}>
      <option value="potentialV">{ko?"전위 (V)":"Potential (V)"}</option><option value="electronsCm3">log₁₀(n / cm⁻³)</option><option value="netDopingCm3">{ko?"부호 있는 log₁₀(1+|도핑|/cm⁻³)":"Signed log₁₀(1+|doping|/cm⁻³)"}</option></select></label>
      <label><input type="checkbox" checked={mesh} onChange={e=>setMesh(e.target.checked)} />{ko?"메시 표시":"Show mesh"}</label></div>
    <svg viewBox="0 0 920 460" role="img" aria-label={ko?"실리콘과 산화막의 실제 2D 계산 지도":"Computed silicon and oxide 2D map"}>
      {si.triangles.map((tri,i)=>{const value=tri.reduce((sum,n)=>sum+values[n],0)/3;return <polygon key={i} points={tri.map(n=>`${x(si.xUm[n])},${y(si.yUm[n])}`).join(" ")} fill={`hsl(${240-220*(value-lo)/(hi-lo||1)} 75% 58%)`} stroke={mesh?"#193244":"none"} strokeWidth=".35"><title>{value.toPrecision(5)}</title></polygon>;})}
      {result.regions.oxide.triangles.map((tri,i)=><polygon key={`ox${i}`} points={tri.map(n=>`${x(result.regions.oxide.xUm[n])},${y(result.regions.oxide.yUm[n])}`).join(" ")} fill="#b8dbea" stroke={mesh?"#193244":"none"} strokeWidth=".35" />)}
      {Object.entries(contacts).map(([name,edges])=><g key={name}><path d={edges.map(([a,b])=>`M${x(a[0])} ${y(a[1])} L${x(b[0])} ${y(b[1])}`).join(" ")} stroke="#ffca67" strokeWidth="5"><title>{name}</title></path><text x={x(edges.reduce((s,[a,b])=>s+(a[0]+b[0])/2,0)/edges.length)} y={name==="body"?425:55} textAnchor="middle">{name[0].toUpperCase()}</text></g>)}
      <text x="460" y="450" textAnchor="middle">x: {xmin.toPrecision(4)} → {xmax.toPrecision(4)} μm</text><text x="15" y="255" transform="rotate(-90 15 255)">y: {ymin.toPrecision(3)} → {ymax.toPrecision(3)} μm</text>
    </svg><p>{lo.toPrecision(4)} ({ko?"파랑":"blue"}) → {hi.toPrecision(4)} ({ko?"주황":"orange"}). {ko?"세로축 확대, 산화막은 연한 파랑. 셀 색은 정점 값의 평균입니다.":"Vertical axis enlarged; oxide shown in pale blue. Cell colors average vertex values."}</p>
  </figure>;
}

export function MosPanel({locale,token}:{locale:"en"|"ko";token:string|null}) {
  const ko=locale==="ko";
  const [input,setInput]=useState<MosInput>(defaultMos),[job,setJob]=useState<MosJob|null>(null),[error,setError]=useState(false),[sending,setSending]=useState(false);
  const [pending,setPending]=useState<MosInput|null>(null),[profile,setProfile]=useState<string|null>(null),[meshHash,setMeshHash]=useState<string|null>(null);
  const originalMesh=input.dopingMode==="suprem-mesh";
  const active=useRef<string|null>(null),running=sending || job?.state==="running";
  let valid=true;try{validateMos(input);}catch{valid=false;}
  useEffect(()=>{if(!token)return;let closed=false;void labRequest(token,"/v1/lab/status").then(v=>{const status=v as {supremProfileSha256?:unknown;supremMeshSha256?:unknown};if(closed)return;for(const [hash,setter] of [[status.supremProfileSha256,setProfile],[status.supremMeshSha256,setMeshHash]] as const)if(typeof hash==="string" && /^[a-f0-9]{64}$/u.test(hash))setter(hash);}).catch(()=>{});return()=>{closed=true;};},[token]);
  useEffect(()=>{
    if(!token || job?.state!=="running")return;
    const controller=new AbortController();
    const timer=window.setTimeout(async()=>{try{setJob(decodeMosJob(await labRequest(token,`/v1/lab/jobs/${job.requestId}`,undefined,controller.signal),job.requestId));setError(false);}catch(failure){if(!controller.signal.aborted){setError(true);if(failure instanceof Error && failure.message==="HTTP 404")setJob({...job,state:"failed"});}}},700);
    return()=>{window.clearTimeout(timer);controller.abort();};
  },[job,token]);
  useEffect(()=>()=>{if(token && active.current)void labRequest(token,`/v1/lab/jobs/${active.current}/cancel`,{}).catch(()=>{});},[token]);
  const change=(next:MosInput)=>{setInput(next);setJob(null);setError(false);};
  const run=async()=>{
    if(!token || running || !valid)return;
    const id=crypto.randomUUID();active.current=id;setSending(true);setJob(null);setError(false);
    try{setJob(decodeMosJob(await labRequest(token,"/v1/lab/jobs",{requestId:id,input}),id));}
    catch(failure){setError(true);if(!(failure instanceof Error && failure.message.startsWith("HTTP ")))setJob({requestId:id,state:"running"});}
    finally{setSending(false);}
  };
  const labels:Record<keyof typeof mosLimits,string>=ko?{gateLengthUm:"게이트 길이 (μm)",widthUm:"소자 폭 (μm)",oxideNm:"산화막 두께 (nm)",acceptorsCm3:"기판 억셉터 (cm⁻³)",donorsCm3:"소스·드레인 피크 도너 (cm⁻³)",gateV:"게이트 전압 (V)",drainV:"드레인 스윕 최종 전압 (V)"}:{gateLengthUm:"Gate length (μm)",widthUm:"Device width (μm)",oxideNm:"Oxide thickness (nm)",acceptorsCm3:"Substrate acceptors (cm⁻³)",donorsCm3:"Source/drain peak donors (cm⁻³)",gateV:"Gate voltage (V)",drainV:"Final drain sweep voltage (V)"};
  const result=job?.state==="complete"?job.result:null;
  return <section className="lab-solver" aria-label="2D MOSFET"><h2>{ko?"2D MOSFET 해석":"2D MOSFET simulation"}</h2><p>{ko?"게이트·산화막·실리콘 구조의 Poisson 및 전자·정공 연속 방정식을 풉니다. 입력 변경 후 실행하면 전류 곡선과 공간 지도를 다시 계산합니다.":"Solve Poisson and electron/hole continuity in a gate/oxide/silicon structure. Change inputs and run to recompute the current curve and spatial fields."}</p>
    {!token && <p>{ko?"정적 페이지에서는 솔버를 실행하지 않습니다. 로컬 서비스가 표시하는 주소로 접속하세요.":"The static page cannot run solvers. Open the address printed by the local service."} <code>npm run local:lab</code></p>}
    <div className="lab-inputs"><label>{ko?"도핑·형상 출처":"Doping and geometry source"}<select disabled={running} value={input.dopingMode} onChange={e=>{const mode=e.target.value as MosInput["dopingMode"];change(mode==="suprem-mesh"?{...defaultMos,widthUm:input.widthUm,gateV:input.gateV,drainV:input.drainV,dopingMode:mode}:{...input,dopingMode:mode});}}><option value="template">{ko?"기본 해석 템플릿":"Analytic template"}</option><option value="suprem" disabled={!profile}>{ko?"SUPREM 활성 도핑 가져오기":"Imported SUPREM active doping"}</option><option value="suprem-mesh" disabled={!meshHash}>{ko?"SUPREM 원본 메시·접촉":"Original SUPREM mesh and contacts"}</option></select></label>
      {(Object.keys(mosLimits) as (keyof typeof mosLimits)[]).filter(key=>!originalMesh || ["widthUm","gateV","drainV"].includes(key)).map(key=><label key={key}>{labels[key]}<input type="number" step="any" min={mosLimits[key][0]} max={mosLimits[key][1]} disabled={running || (input.dopingMode==="suprem" && ["acceptorsCm3","donorsCm3"].includes(key))} value={Number.isFinite(input[key])?input[key]:""} onChange={e=>change({...input,[key]:e.target.valueAsNumber})} /><small>{mosLimits[key][0]} ~ {mosLimits[key][1]}</small></label>)}
      {!originalMesh && <label>{ko?"메시 세분화":"Mesh refinement"}<select disabled={running} value={input.refinement} onChange={e=>change({...input,refinement:Number(e.target.value)})}><option value="1">1×</option><option value="2">2×</option></select></label>}</div>
    <p>{ko?"SUPREM 연계: --suprem-structure로 구조 파일을 지정하고, 원본 메시 해석에는 --suprem-contacts로 해시에 묶인 전극 경계를 추가합니다. 실리콘 1영역·산화막 1영역 구조를 지원합니다.":"SUPREM coupling: use --suprem-structure for the structure, and --suprem-contacts for hash-bound electrodes when solving the original mesh. Supports one silicon and one oxide region."}</p>
    {originalMesh && <p>{ko?"형상·도핑·메시 간격은 공정 파일에서 가져옵니다. 숨겨진 템플릿 입력은 사용하지 않으며 변경하려면 공정을 다시 실행해야 합니다. 표시 전극은 지정된 실제 경계입니다.":"Geometry, doping and mesh spacing come from the process file. Hidden template inputs are unused; rerun the process to change them. Electrodes follow the explicitly assigned boundaries."} <code className="mos-hash">{meshHash}</code></p>}
    {input.dopingMode==="suprem" && <p>{ko?"기판·도너 입력값은 사용하지 않습니다. 전체 실리콘 영역을 덮지 않는 파일은 실패합니다.":"Substrate/donor input values are unused. Files not covering the full silicon domain fail."} SHA-256: <code className="mos-hash">{profile}</code></p>}
    {!valid && <p role="alert">{ko?"입력 범위를 확인하세요.":"Check input ranges."}</p>}
    <div className="m4-toolbar"><button className="primary-button" disabled={!token || running || !valid || (input.dopingMode==="suprem" && !profile) || (originalMesh && !meshHash)} onClick={run}>{ko?"2D MOSFET 실행":"Run 2D MOSFET"}</button><button className="quiet-button" disabled={!token || job?.state!=="running"} onClick={async()=>{try{setJob(decodeMosJob(await labRequest(token!,`/v1/lab/jobs/${job!.requestId}/cancel`,{}),job!.requestId));setError(false);}catch{setError(true);}}}>{ko?"2D 해석 취소":"Cancel 2D solve"}</button></div>
    <p role="status">{sending?(ko?"제출 중":"Submitting"):job?({running:ko?"실제 2D 해석 중":"Solving 2D equations",complete:ko?"2D 해석 완료":"2D solve complete",failed:ko?"수렴 또는 실행 실패":"Convergence or execution failure",cancelled:ko?"취소됨":"Cancelled"})[job.state]:""}</p>
    {error && <div role="alert"><p>{ko?"실행 요청을 확인하지 못했습니다. 다른 해석 실행 여부, 입력, 수렴 및 서버 연결을 확인하세요. 통신 실패는 취소 완료를 뜻하지 않습니다.":"Could not confirm the request. Check other active jobs, inputs, convergence and service connection. A transport failure does not mean cancellation."}</p>{job?.state==="running" && <button className="quiet-button" onClick={()=>setJob({...job})}>{ko?"상태 다시 확인":"Recheck status"}</button>}</div>}
    {result && <><p>{ko?"드레인 전류":"Drain current"}: <strong>{(result.iv.at(-1)![1]*1e6).toPrecision(5)} μA</strong> · {result.checks.siliconNodes} {ko?"실리콘 노드":"silicon nodes"}</p><MosMap result={result} ko={ko} /><NumericPlot points={result.iv.map(([v,i])=>[v,i*1e6])} title="ID–VD" xLabel="VD (V)" yLabel="ID (μA)" />
      <details><summary>{ko?"수치 검증·재현 정보":"Numerical checks and provenance"}</summary><pre className="lab-provenance">{JSON.stringify({input:result.input,dopingSource:result.dopingSource,checks:result.checks,environment:result.environment,templateSha256:result.templateSha256,resultSha256:result.resultSha256},null,2)}</pre></details>
      <button className="quiet-button" onClick={()=>{try{downloadWorkspaceJson(JSON.stringify(result),"opentcad-mos-result.json");}catch{setError(true);}}}>{ko?"2D 결과 저장":"Save 2D result"}</button></>}
    <label className="file-field">{ko?"2D 결과에서 입력 불러오기":"Load inputs from a 2D result"}<input type="file" accept=".json" disabled={running} onChange={async e=>{const file=e.target.files?.[0];e.target.value="";setPending(null);if(!file)return;try{const r=parseWorkspaceJson(await readWorkspaceFile(file),120000) as Record<string,unknown>;if(r.format!=="opentcad-mos-result" || r.schemaVersion!==1 || r.model!==MOS_MODEL)throw new Error("format");setPending(validateMos(r.input));}catch{setError(true);}}}/></label>
    {pending && <div className="import-review"><p>{ko?"입력만 교체합니다. 저장된 결과는 실행 결과로 간주하지 않습니다.":"Replace inputs only. Stored results are not treated as a fresh solve."}</p><pre>{JSON.stringify(pending,null,2)}</pre><button className="quiet-button" disabled={running} onClick={()=>{change(pending);setPending(null);}}>{ko?"입력 적용":"Apply inputs"}</button><button className="quiet-button" onClick={()=>setPending(null)}>{ko?"닫기":"Dismiss"}</button></div>}
    <p className="lab-warning">{ko?"300 K, 고정 이동도, 이상적 접촉, SRH 재결합, 금속 게이트 전위 오프셋 +0.45 V를 사용합니다. 양자 효과·고전계 이동도·항복·터널링은 포함하지 않습니다. SUPREM 파일 출처와 공정 실행 승인은 별개이며 제품 자격은 미승인 상태입니다.":"300 K, constant mobility, ideal contacts, SRH recombination and a +0.45 V metal-gate potential offset. No quantum effects, high-field mobility, breakdown or tunneling. An imported SUPREM file is not proof of process execution approval. Product qualification remains unapproved."}</p>
  </section>;
}
