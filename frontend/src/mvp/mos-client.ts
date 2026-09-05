import { boundedNumber, exactRecord } from "../m4/files";
export const MOS_MODEL = "devsim-mos-2d-300K-v1";
export const mosLimits = {gateLengthUm:[.5,2],widthUm:[1,100],oxideNm:[5,30],acceptorsCm3:[1e15,1e17],donorsCm3:[1e17,1e18],gateV:[0,1.5],drainV:[0,.5]} as const;
export type MosInput = Record<keyof typeof mosLimits,number> & {model:typeof MOS_MODEL;refinement:number;dopingMode:"template"|"suprem"};
export const defaultMos: MosInput = {model:MOS_MODEL,gateLengthUm:1,widthUm:10,oxideNm:10,acceptorsCm3:1e16,donorsCm3:1e18,gateV:1,drainV:.1,refinement:1,dopingMode:"template"};
export function validateMos(value:unknown): MosInput {
  const r=exactRecord(value,[...Object.keys(mosLimits),"model","refinement","dopingMode"]);
  if(r.model!==MOS_MODEL || ![1,2].includes(r.refinement as number) || !["template","suprem"].includes(r.dopingMode as string)) throw new Error("mos-input");
  for(const [k,[a,b]] of Object.entries(mosLimits)) boundedNumber(r[k],a,b);
  return r as unknown as MosInput;
}
export interface MosRegion {xUm:number[];yUm:number[];triangles:[number,number,number][];potentialV:number[];electronsCm3?:number[];holesCm3?:number[];netDopingCm3?:number[]}
export interface MosResult {format:"opentcad-mos-result";schemaVersion:1;model:typeof MOS_MODEL;input:MosInput;solver:"DEVSIM";solverVersion:string;
  inputSha256:string;templateSha256:string;resultSha256:string;environment:Record<string,string>;constants:Record<string,number>;units:Record<string,string>;
  dopingSource:{kind:string;processSimulated:false;sourceSha256?:string};regions:{silicon:MosRegion;oxide:MosRegion};iv:[number,number][];
  contactCurrentsA:Record<string,number>[];checks:Record<string,number>;productApproved:false;}
export function decodeMosResult(value:unknown):MosResult {
  const r=exactRecord(value,["format","schemaVersion","model","input","solver","solverVersion","inputSha256","templateSha256","resultSha256","environment","constants","units","dopingSource","regions","iv","contactCurrentsA","checks","productApproved"]);
  const input=validateMos(r.input);
  if(r.format!=="opentcad-mos-result" || r.schemaVersion!==1 || r.model!==MOS_MODEL || r.solver!=="DEVSIM" || r.solverVersion!=="2.11.0" || r.productApproved!==false) throw new Error("mos-result");
  for(const key of ["inputSha256","templateSha256","resultSha256"]) if(typeof r[key]!=="string" || !/^[a-f0-9]{64}$/u.test(r[key])) throw new Error("digest");
  const units=exactRecord(r.units,["length","potential","density","current"]);
  if(units.length!=="um" || units.potential!=="V" || units.density!=="cm^-3" || units.current!=="A") throw new Error("units");
  const env=exactRecord(r.environment,["python","os","machine"]);
  if(Object.values(env).some(v=>typeof v!=="string" || v.length>80)) throw new Error("environment");
  const constants=exactRecord(r.constants,["temperatureK","gateOffsetV","muN","muP","niCm3"]);
  if(constants.temperatureK!==300 || constants.gateOffsetV!==.45 || constants.muN!==400 || constants.muP!==200 || constants.niCm3!==1e10) throw new Error("constants");
  const source=exactRecord(r.dopingSource,input.dopingMode==="template"?["kind","processSimulated"]:["kind","processSimulated","sourceSha256","transfer","geometry"]);
  if(source.processSimulated!==false || source.kind!==(input.dopingMode==="template"?"analytic-template":"suprem-str-import")) throw new Error("source");
  if(input.dopingMode==="suprem" && (typeof source.sourceSha256!=="string" || !/^[a-f0-9]{64}$/u.test(source.sourceSha256) || source.transfer!=="barycentric-active-doping" || source.geometry!=="template-remesh")) throw new Error("process-source");
  const regions=exactRecord(r.regions,["silicon","oxide"]);
  for(const name of ["silicon","oxide"]) {
    const keys=["xUm","yUm","potentialV",...(name==="silicon"?["electronsCm3","holesCm3","netDopingCm3"]:[])];
    const region=exactRecord(regions[name],[...keys,"triangles"]);
    if(!Array.isArray(region.xUm) || region.xUm.length<4 || region.xUm.length>5000) throw new Error("mesh-size");
    const count=region.xUm.length;
    for(const key of keys) {
      const arr=region[key]; if(!Array.isArray(arr) || arr.length!==count) throw new Error("mesh-array");
      arr.forEach(v=>boundedNumber(v,key==="electronsCm3" || key==="holesCm3"?Number.MIN_VALUE:-1e30,1e30));
    }
    (region.xUm as number[]).forEach(v=>boundedNumber(v,-1e-9,input.gateLengthUm+1+1e-9));
    (region.yUm as number[]).forEach(v=>boundedNumber(v,name==="silicon"?-1e-9:-input.oxideNm*.001-1e-9,name==="silicon"?.500000001:1e-9));
    if(!Array.isArray(region.triangles) || region.triangles.length<2 || region.triangles.length>10000) throw new Error("triangles");
    for(const tri of region.triangles) {
      if(!Array.isArray(tri) || tri.length!==3 || new Set(tri).size!==3 || tri.some(v=>!Number.isInteger(v) || v<0 || v>=count)) throw new Error("triangle");
    }
  }
  const size=Math.max(1,Math.ceil(input.drainV/.025))+1;
  if(!Array.isArray(r.iv) || r.iv.length!==size || !Array.isArray(r.contactCurrentsA) || r.contactCurrentsA.length!==size) throw new Error("iv");
  r.iv.forEach((point,i)=>{if(!Array.isArray(point) || point.length!==2) throw new Error("point"); boundedNumber(point[1],-1e10,1e10); boundedNumber(point[0],0,.5); if(Math.abs(point[0]-input.drainV*i/(size-1))>1e-12) throw new Error("sweep");});
  r.contactCurrentsA.forEach(v=>Object.values(exactRecord(v,["source","drain","body"])).forEach(n=>boundedNumber(n,-1e10,1e10)));
  const checks=exactRecord(r.checks,["maxCurrentToleranceRatio","siliconNodes"]);
  boundedNumber(checks.maxCurrentToleranceRatio,0,1);
  if(checks.siliconNodes!==(regions.silicon as MosRegion).xUm.length) throw new Error("nodes");
  return r as unknown as MosResult;
}
export interface MosJob {requestId:string;state:"running"|"complete"|"cancelled"|"failed";result?:MosResult}
export function decodeMosJob(value:unknown,id:string):MosJob {
  if(!value || typeof value!=="object") throw new Error("job");
  const r=value as MosJob;
  if(r.requestId!==id || !["running","complete","cancelled","failed"].includes(r.state)) throw new Error("job");
  return r.state==="complete"?{...r,result:decodeMosResult(r.result)}:r;
}
