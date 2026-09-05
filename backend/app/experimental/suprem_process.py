"""Explicit local CLI only: fixed SUPREM deck, never accepts browser code.

This does not sandbox the user-installed executable. It does not redistribute
SUPREM or approve its license. Run only an installation you trust and may use.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from .contract import canonical, digest
from .suprem import read_structure

def deck(gate_length=1., dose=1e14, energy=30., minutes=10., temperature=950.):
    values = (gate_length,dose,energy,minutes,temperature)
    bounds = ((.5,2),(1e13,1e15),(10,80),(1,30),(850,1050))
    if any(type(v) not in (int,float) or not math.isfinite(v) or not a<=v<=b for v,(a,b) in zip(values,bounds)):
        raise ValueError("process-input-range")
    length, left, right = gate_length+1,.5,.5+gate_length
    # Fixed rectangular silicon and temporary implant mask. The gate dielectric
    # is added by DEVSIM, not claimed as a SUPREM-grown oxide.
    return f"""line x loc=0 spacing=0.05 tag=left
line x loc={left:.12g} spacing=0.025
line x loc={right:.12g} spacing=0.025
line x loc={length:.12g} spacing=0.05 tag=right
line y loc=0 spacing=0.005 tag=top
line y loc=0.15 spacing=0.02
line y loc=0.5 spacing=0.05 tag=bottom
region silicon xlo=left xhi=right ylo=top yhi=bottom
bound exposed xlo=left xhi=right ylo=top yhi=top
bound backside xlo=left xhi=right ylo=bottom yhi=bottom
initialize boron conc=1e16 ori=100
deposit oxide thick=0.3
etch oxide left p1.x={left:.12g}
etch oxide right p1.x={right:.12g}
implant phosphorus dose={dose:.12g} energy={energy:.12g}
etch oxide all
diffuse time={minutes:.12g} temp={temperature:.12g}
structure out=process.str
quit
"""

async def execute(executable, data_directory, output, *, gate_length=1., dose=1e14, energy=30., minutes=10., temperature=950., timeout=120):
    executable=Path(executable).resolve(strict=True)
    data_directory=Path(data_directory).resolve(strict=True)
    if not executable.is_file(): raise ValueError("suprem-executable")
    data={k:data_directory/name for k,name in {"SUP4KEYFILE":"suprem.uk","SUP4MODELRC":"modelrc","SUP4IMPDATA":"sup4gs.imp"}.items()}
    if not all(p.is_file() for p in data.values()): raise ValueError("suprem-data")
    script=deck(gate_length,dose,energy,minutes,temperature)
    # A new explicit output directory only; never overwrite existing results.
    output=Path(output).resolve()
    output.mkdir(parents=False,exist_ok=False)
    env={k:v for k,v in os.environ.items() if k.upper() in {"PATH","SYSTEMROOT","WINDIR","TEMP","TMP","PATHEXT"}}
    env.update({k:str(v) for k,v in data.items()})
    hashes={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in data.items()}
    executable_hash=hashlib.sha256(executable.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="opentcad-suprem-") as temporary:
        launch=asyncio.create_task(asyncio.create_subprocess_exec(str(executable),cwd=temporary,env=env,
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0))
        try:
            process=await asyncio.shield(launch)
        except asyncio.CancelledError:
            process=await launch
            if process.returncode is None: process.kill()
            await process.wait()
            raise
        async def communicate():
            process.stdin.write(script.encode("ascii")); await process.stdin.drain(); process.stdin.close()
            size=0
            while chunk:=await process.stdout.read(65536):
                size+=len(chunk)
                if size>2_097_152: raise ValueError("suprem-log-limit")
            await process.wait()
            if process.returncode: raise ValueError("suprem-failed")
        try:
            await asyncio.wait_for(communicate(),timeout)
            path=Path(temporary)/"process.str"
            profile=read_structure(path)
            # Re-check code/data bytes: never bless a moving solver installation.
            if executable_hash!=hashlib.sha256(executable.read_bytes()).hexdigest() or any(hashes[k]!=hashlib.sha256(v.read_bytes()).hexdigest() for k,v in data.items()):
                raise ValueError("suprem-installation-changed")
            record={"format":"opentcad-suprem-process","schemaVersion":1,"executableSha256":executable_hash,
                    "dataSha256":hashes,"deckSha256":hashlib.sha256(script.encode("ascii")).hexdigest(),
                    "structureSha256":profile["sourceSha256"],"gateLengthUm":gate_length,"productApproved":False}
            record["recordSha256"]=digest(record)
            (output/"process.str").write_bytes(path.read_bytes())
            (output/"process.in").write_text(script,encoding="ascii")
            (output/"process.json").write_bytes(canonical(record))
            return record
        finally:
            if process.returncode is None:
                try: process.kill()
                except ProcessLookupError: pass
            await process.wait()

def main():
    parser=argparse.ArgumentParser(description="Run a trusted, user-installed SUPREM with a code-owned implant/anneal deck")
    parser.add_argument("--enable-experimental-suprem",action="store_true",required=True)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--data-directory",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    for name,default in (("gate-length",1.),("dose",1e14),("energy",30.),("minutes",10.),("temperature",950.)):
        parser.add_argument("--"+name,type=float,default=default)
    args=parser.parse_args()
    try:
        record=asyncio.run(execute(args.executable,args.data_directory,args.output,gate_length=args.gate_length,
            dose=args.dose,energy=args.energy,minutes=args.minutes,temperature=args.temperature))
        print(json.dumps(record,sort_keys=True)); return 0
    except (Exception,KeyboardInterrupt):
        print("SUPREM process failed; no validated result. Check installation, permissions, deck support and output directory.")
        return 1

if __name__=="__main__": raise SystemExit(main())
