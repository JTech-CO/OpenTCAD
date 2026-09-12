import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,describe,expect,it,vi} from "vitest";
import {decodeHistory,HistoryPanel} from "./HistoryPanel";
import {defaultPn,PN_MODEL} from "./solver-client";
import App from "../App";

afterEach(() => {cleanup();vi.unstubAllGlobals();});
const id = "00000000-0000-4000-8000-000000000001";
const row = {requestId:id,state:"complete",inputSha256:"a".repeat(64)};
function fixture() {
  const x = Array.from({length:101},(_,i)=>i*.02);
  return {format:"opentcad-solver-result",schemaVersion:1,model:PN_MODEL,input:{...defaultPn,voltageV:0,intervals:100},
    solver:"DEVSIM",solverVersion:"2.11.0",inputSha256:row.inputSha256,templateSha256:"b".repeat(64),resultSha256:"c".repeat(64),
    environment:{python:"fixture",os:"fixture",machine:"fixture"},constants:{temperatureK:300,niCm3:1e10,muN:400,muP:200,lifetimeS:1e-6,epsilonFcm:1e-12,qC:1.6e-19,kJK:1.38e-23},units:{x:"um",potential:"V",density:"cm^-3",current:"A"},
    iv:[[0,0],[0,0]],xUm:x,potentialV:x,equilibriumPotentialV:x,electronsCm3:x.map(()=>1e16),holesCm3:x.map(()=>1e4),netDopingCm3:x.map(()=>1e16),checks:{builtInExpectedV:.7,builtInComputedV:.7,builtInErrorV:0,maxCurrentToleranceRatio:0,nodeCount:101},productApproved:false};
}
describe("retained solver workflow",()=>{
  it("reconnects from a new private fragment in the same tab and scrubs it",async()=>{
    window.localStorage.setItem("opentcad-locale","en");
    window.history.replaceState(null,"","/#lab");
    vi.stubGlobal("fetch",vi.fn(async()=>({ok:true,text:async()=>JSON.stringify({})})));
    render(<App/>);
    expect(screen.getByRole("button",{name:"Run DEVSIM solve"})).toBeDisabled();
    window.history.replaceState(null,"","/#experiment="+"A".repeat(43));
    fireEvent(window,new HashChangeEvent("hashchange"));
    expect(screen.getByRole("button",{name:"Run DEVSIM solve"})).toBeEnabled();
    expect(window.location.hash).toBe("#lab");
    window.history.replaceState(null,"","/");
  });
  it.each(["en","ko"] as const)("reopens computed data without executing or replacing inputs (%s)",async locale=>{
    const fetcher = vi.fn(async (url:string)=>({ok:true,text:async()=>JSON.stringify(url.endsWith(id)?{...row,result:fixture()}:{jobs:[row]})}));
    vi.stubGlobal("fetch",fetcher);
    render(<HistoryPanel locale={locale} token={"A".repeat(43)}/>);
    fireEvent.click(screen.getByRole("button",{name:locale==="ko"?"이력 새로고침":"Refresh history"}));
    fireEvent.click(await screen.findByRole("button",{name:locale==="ko"?"결과 열기":"Open result"}));
    await screen.findByText(locale==="ko"?"저장된 I-V":"Stored I-V");
    fireEvent.click(screen.getByRole("button",{name:locale==="ko"?"비교 기준으로 지정":"Set comparison baseline"}));
    expect(screen.getByText("ΔI")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.every(call=>(call as unknown as [string,RequestInit])[1].method==="GET")).toBe(true);
  });
  it("keeps the static page disconnected",()=>{
    const fetcher=vi.fn();vi.stubGlobal("fetch",fetcher);
    render(<HistoryPanel locale="en" token={null}/>);
    expect(screen.getByRole("button",{name:"Refresh history"})).toBeDisabled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("rejects malformed duplicate and oversized summaries",()=>{
    for(const value of [{jobs:[row,row]},{jobs:[{...row,requestId:"../../x"}]},{jobs:Array(33).fill(row)},{jobs:[{...row,result:{}}]}])expect(()=>decodeHistory(value)).toThrow();
  });
  it("does not display a mismatched stored result",async()=>{
    vi.stubGlobal("fetch",vi.fn(async(url:string)=>({ok:true,text:async()=>JSON.stringify(url.endsWith(id)?{...row,result:{...fixture(),inputSha256:"f".repeat(64)}}:{jobs:[row]})})));
    render(<HistoryPanel locale="en" token={"A".repeat(43)}/>);
    fireEvent.click(screen.getByRole("button",{name:"Refresh history"}));
    fireEvent.click(await screen.findByRole("button",{name:"Open result"}));
    await screen.findByRole("alert");
    expect(screen.queryByText("Stored I-V")).not.toBeInTheDocument();
  });
});
