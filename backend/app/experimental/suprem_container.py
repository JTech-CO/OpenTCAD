"""Opt-in local-only SUPREM container transport, never M3 runtime activation.

Requires an already present immutable image with /opt/suprem4gs layout, shell
and coreutils. No pull, host bind mounts, supplied decks or network access.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .contract import canonical, digest
from .suprem import parse_structure
from .suprem_process import deck

# These shell commands are code-owned and receive no string interpolation.
SCRIPT = '''set -eu
printf 'OPENTCAD_FILES_BEGIN\\n'
sha256sum /opt/suprem4gs/suprem /opt/suprem4gs/data/suprem.uk /opt/suprem4gs/data/modelrc /opt/suprem4gs/data/sup4gs.imp
printf 'OPENTCAD_FILES_END\\n'
/opt/suprem4gs/suprem
test -s /work/process.str
printf '\\nOPENTCAD_STR_BEGIN\\n'
cat /work/process.str
printf '\\nOPENTCAD_STR_END\\n'
'''

def command(runtime,image,name):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image): raise ValueError("immutable-image-required")
    return [runtime,"run","--name",name,"--rm","--pull=never","--network=none","--read-only",
            "--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit=64","--memory=512m","--cpus=1",
            "--user=10001:10001","--tmpfs=/work:rw,nosuid,nodev,noexec,size=64m,mode=0777",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777","--workdir=/work",
            "--env=SUP4KEYFILE=/opt/suprem4gs/data/suprem.uk","--env=SUP4MODELRC=/opt/suprem4gs/data/modelrc",
            "--env=SUP4IMPDATA=/opt/suprem4gs/data/sup4gs.imp","--env=SUP4MANDIR=/opt/suprem4gs/help",
            "--interactive","--entrypoint=/bin/sh",image,"-c",SCRIPT]

def decode_output(source):
    def section(start,end):
        first,last=(start+b"\n"),(b"\n"+end)
        if source.count(first)!=1 or source.count(last)!=1: raise ValueError("suprem-output-protocol")
        return source.split(first,1)[1].split(last,1)[0]
    structure=section(b"OPENTCAD_STR_BEGIN",b"OPENTCAD_STR_END")
    profile=parse_structure(structure)
    lines=section(b"OPENTCAD_FILES_BEGIN",b"OPENTCAD_FILES_END").decode("ascii").splitlines()
    names=["/opt/suprem4gs/suprem","/opt/suprem4gs/data/suprem.uk","/opt/suprem4gs/data/modelrc","/opt/suprem4gs/data/sup4gs.imp"]
    files={}
    for line,name in zip(lines,names):
        fields=line.split()
        if len(fields)!=2 or fields[1]!=name or not re.fullmatch(r"[0-9a-f]{64}",fields[0]): raise ValueError("suprem-file-hash")
        files[name]=fields[0]
    if len(lines)!=4: raise ValueError("suprem-file-count")
    return structure,profile,files

async def execute_container(runtime,image,output,*,gate_length=1.,dose=1e14,energy=30.,minutes=10.,temperature=950.,gate_oxide_nm=0.,mesh_refinement=1,timeout=120):
    if runtime not in ("docker","podman"): raise ValueError("runtime")
    executable=shutil.which(runtime)
    if not executable: raise ValueError("runtime-missing")
    name="opentcad-exp-suprem-"+uuid4().hex
    argv=command(executable,image,name)
    script=deck(gate_length,dose,energy,minutes,temperature,gate_oxide_nm,mesh_refinement)
    output=Path(output).resolve();output.mkdir(parents=False,exist_ok=False)
    launch=asyncio.create_task(asyncio.create_subprocess_exec(*argv,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT))
    process=None
    try:
        process=await asyncio.shield(launch)
        async def communicate():
            process.stdin.write(script.encode("ascii"));await process.stdin.drain();process.stdin.close()
            chunks=[];size=0
            while chunk:=await process.stdout.read(65536):
                size+=len(chunk)
                if size>2_097_152:raise ValueError("suprem-output-limit")
                chunks.append(chunk)
            await process.wait()
            if process.returncode: raise ValueError("suprem-container-failed")
            return b"".join(chunks)
        source=await asyncio.wait_for(communicate(),timeout)
        structure,profile,files=decode_output(source)
        record={"format":"opentcad-suprem-process","schemaVersion":1,"imageId":image,"runtime":runtime,
                "filesSha256":files,"deckSha256":hashlib.sha256(script.encode("ascii")).hexdigest(),
                "structureSha256":profile["sourceSha256"],"gateLengthUm":gate_length,"productApproved":False}
        record["recordSha256"]=digest(record)
        (output/"process.str").write_bytes(structure)
        (output/"process.in").write_text(script,encoding="ascii")
        (output/"process.json").write_bytes(canonical(record))
        return record
    finally:
        if process is None:process=await launch
        if process.returncode is None:
            try:process.kill()
            except ProcessLookupError:pass
        await process.wait()
        # Exact per-job UUID target only; never prune images or other containers.
        cleanup=await asyncio.create_subprocess_exec(executable,"rm","--force",name,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try:await asyncio.wait_for(cleanup.wait(),10)
        except TimeoutError:
            cleanup.kill();await cleanup.wait();raise RuntimeError("container-cleanup-timeout")
        # rm can report 'already removed' because run used --rm. Confirm the
        # authoritative list, rather than treating any rm failure as absence.
        verify=await asyncio.create_subprocess_exec(executable,"ps","--all","--filter",f"name={name}","--format","{{.Names}}",stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:
            listing=await asyncio.wait_for(verify.communicate(),10)
        except TimeoutError:
            verify.kill();await verify.wait();raise RuntimeError("container-cleanup-unconfirmed")
        if verify.returncode or listing[0].strip():raise RuntimeError("container-cleanup-unconfirmed")

def main():
    parser=argparse.ArgumentParser(description="Run the fixed experimental SUPREM process in an existing immutable local image")
    parser.add_argument("--enable-experimental-suprem",action="store_true",required=True)
    parser.add_argument("--runtime",choices=("docker","podman"),required=True)
    parser.add_argument("--image",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--gate-oxide-nm",type=float,default=0.)
    parser.add_argument("--lateral-refinement",dest="mesh_refinement",type=int,choices=(1,2),default=1,help="Refine x spacing only; y spacing remains unchanged")
    for name,default in (("gate-length",1.),("dose",1e14),("energy",30.),("minutes",10.),("temperature",950.)):
        parser.add_argument("--"+name,type=float,default=default)
    args=parser.parse_args()
    try:
        print(json.dumps(asyncio.run(execute_container(args.runtime,args.image,args.output,gate_length=args.gate_length,
            dose=args.dose,energy=args.energy,minutes=args.minutes,temperature=args.temperature,gate_oxide_nm=args.gate_oxide_nm,mesh_refinement=args.mesh_refinement)),sort_keys=True));return 0
    except (Exception,KeyboardInterrupt):
        print("SUPREM container failed; no validated process result. Verify the local image, runtime restrictions and supported process commands.")
        return 1

if __name__=="__main__":raise SystemExit(main())
