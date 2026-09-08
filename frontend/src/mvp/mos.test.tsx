import { cleanup,fireEvent,render,screen,waitFor } from "@testing-library/react";
import { afterEach,describe,expect,it,vi } from "vitest";
import { MosMap, MosPanel } from "./MosPanel";
import { decodeMosResult,defaultMos,MOS_MODEL,validateMos } from "./mos-client";
import { parseWorkspaceJson } from "../m4/files";

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
function fixture(){
  const region={xUm:[0,2,2,0],yUm:[0,0,.5,.5],triangles:[[0,1,2],[0,2,3]],potentialV:[.4,.5,-.3,-.3]};
  return {format:"opentcad-mos-result",schemaVersion:1,model:MOS_MODEL,input:defaultMos,solver:"DEVSIM",solverVersion:"2.11.0",
    inputSha256:"a".repeat(64),templateSha256:"b".repeat(64),resultSha256:"c".repeat(64),environment:{python:"test",os:"test",machine:"test"},
    units:{length:"um",potential:"V",density:"cm^-3",current:"A"},constants:{temperatureK:300,gateOffsetV:.45,muN:400,muP:200,niCm3:1e10},
    dopingSource:{kind:"analytic-template",processSimulated:false},regions:{silicon:{...region,electronsCm3:[1e18,1e18,1e4,1e4],holesCm3:[1e2,1e2,1e16,1e16],netDopingCm3:[1e18,1e18,-1e16,-1e16]},oxide:{...region,xUm:[.5,1.5,1.5,.5],yUm:[-.01,-.01,0,0]}},
    iv:[0,.025,.05,.075,.1].map(v=>[v,v*.001]),contactCurrentsA:[0,.025,.05,.075,.1].map(v=>({drain:v*.001,source:-v*.001,body:0})),checks:{maxCurrentToleranceRatio:0,siliconNodes:4},productApproved:false};
}
describe("2D MOS laboratory",()=>{
  it("validates original-mesh provenance and uses supplied contact coordinates",()=>{
    const base=fixture();
    const result={...base,input:{...defaultMos,dopingMode:"suprem-mesh"},
      dopingSource:{kind:"suprem-str-import",processSimulated:false,sourceSha256:"d".repeat(64),meshSha256:"e".repeat(64),contactsSha256:"f".repeat(64),transfer:"original-node-active-doping",geometry:"original-silicon-oxide-mesh"},
      contactSegmentsUm:{source:[[[0,0],[2,0]]],drain:[[[2,0],[2,.5]]],body:[[[0,.5],[2,.5]]],gate:[[[.5,-.01],[1.5,-.01]]]},
      meshChecks:{triangleCounts:{silicon:2,oxide:2},areasUm2:{silicon:1,oxide:.01},nodalDopingTransferredExactly:true}};
    expect(decodeMosResult(result).contactSegmentsUm?.gate).toEqual(result.contactSegmentsUm.gate);
    render(<MosMap result={decodeMosResult(result)} ko={false}/>);
    expect(screen.getByText("gate").parentElement).toHaveAttribute("d","M260 80 L660 80");
    expect(()=>decodeMosResult({...result,dopingSource:{...result.dopingSource,meshSha256:"invalid"}})).toThrow();
    expect(()=>decodeMosResult({...result,contactSegmentsUm:{...result.contactSegmentsUm,gate:[[[.4,-.01],[1.5,-.01]]]}})).toThrow();
  });
  it.each(["en","ko"] as const)("allows only bias and width edits for configured process geometry (%s)",async locale=>{
    vi.stubGlobal("fetch",vi.fn(async()=>({ok:true,text:async()=>JSON.stringify({supremProfileSha256:"a".repeat(64),supremMeshSha256:"b".repeat(64)})})));
    render(<MosPanel locale={locale} token={"A".repeat(43)}/>);
    const name=locale==="ko"?"SUPREM 원본 메시·접촉":"Original SUPREM mesh and contacts";
    await waitFor(()=>expect(screen.getByRole("option",{name})).toBeEnabled());
    fireEvent.change(screen.getByRole("combobox",{name:locale==="ko"?"도핑·형상 출처":"Doping and geometry source"}),{target:{value:"suprem-mesh"}});
    expect(screen.getAllByRole("spinbutton")).toHaveLength(3);
    expect(screen.getByRole("button",{name:locale==="ko"?"2D MOSFET 실행":"Run 2D MOSFET"})).toBeEnabled();
  });
  it("validates physical inputs, dimensions, materials and provenance",()=>{
    expect(decodeMosResult(fixture()).regions.silicon.triangles).toHaveLength(2);
    for(const p of [{...defaultMos,command:"id"},{...defaultMos,gateV:NaN},{...defaultMos,refinement:3}])expect(()=>validateMos(p)).toThrow();
    const bad=fixture();bad.regions.silicon.triangles[0][2]=5;expect(()=>decodeMosResult(bad)).toThrow();
    const nan=fixture();nan.regions.silicon.potentialV[0]=NaN;expect(()=>decodeMosResult(nan)).toThrow();
    const source=fixture();source.dopingSource.kind="suprem-str-import";expect(()=>decodeMosResult(source)).toThrow();
    const units=fixture();units.units.length="cm";expect(()=>decodeMosResult(units)).toThrow();
  });
  it("supports bounded dense-result imports without changing default file limits",()=>{
    const text=JSON.stringify({data:Array(30000).fill(1)});
    expect(()=>parseWorkspaceJson(text)).toThrow();
    expect(parseWorkspaceJson(text,120000)).toHaveProperty("data");
    expect(()=>parseWorkspaceJson('{"input":1,"input":2}',120000)).toThrow();
  });
  it.each(["en","ko"] as const)("does not pretend to solve on the static site (%s)",locale=>{
    const fetcher=vi.fn();vi.stubGlobal("fetch",fetcher);
    render(<MosPanel locale={locale} token={null}/>);
    expect(screen.getByRole("button",{name:locale==="ko"?"2D MOSFET 실행":"Run 2D MOSFET"})).toBeDisabled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("submits, polls, displays real-result contract and clears stale results on edit",async()=>{
    let id="";
    const fetcher=vi.fn(async(url:string,options:RequestInit)=>{
      if(url.endsWith("/status"))return {ok:true,text:async()=>JSON.stringify({supremProfileSha256:null})};
      if(options.method==="POST")id=JSON.parse(options.body as string).requestId ?? id;
      return {ok:true,text:async()=>JSON.stringify({requestId:id,state:options.method==="POST"?"running":"complete",...(options.method==="GET"?{result:fixture()}:{})})};
    });vi.stubGlobal("fetch",fetcher);
    render(<MosPanel locale="en" token={"A".repeat(43)}/>);
    fireEvent.click(screen.getByRole("button",{name:"Run 2D MOSFET"}));
    await screen.findByText("2D solve complete",{},{timeout:3000});
    expect(screen.getByRole("img",{name:"Computed silicon and oxide 2D map"})).toBeInTheDocument();
    expect(JSON.parse(fetcher.mock.calls.find(([url])=>url==="/v1/lab/jobs")![1].body as string).input).toEqual(defaultMos);
    fireEvent.change(screen.getByRole("combobox",{name:"Displayed field"}),{target:{value:"electronsCm3"}});
    fireEvent.change(screen.getByRole("spinbutton",{name:/Gate voltage/}),{target:{value:".8"}});
    expect(screen.queryByText("2D solve complete")).not.toBeInTheDocument();
  });
  it("exposes cancel and recheck after a transport failure",async()=>{
    vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new Error("offline")));
    render(<MosPanel locale="en" token={"A".repeat(43)}/>);
    fireEvent.click(screen.getByRole("button",{name:"Run 2D MOSFET"}));
    await waitFor(()=>expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("button",{name:"Cancel 2D solve"})).toBeEnabled();
    expect(screen.getByRole("button",{name:"Recheck status"})).toBeInTheDocument();
  });
});
