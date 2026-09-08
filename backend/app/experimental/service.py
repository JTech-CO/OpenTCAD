"""Opt-in loopback service for code-owned DEVSIM templates, not M3 activation."""
import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import UUID

from backend.app.service.local_api import LocalApiBind, LocalApiServer, LocalBrokerApi
from backend.app.service.static_assets import LocalStaticAssets
from backend.app.service.cli import _stop_event
from .contract import MODEL, canonical, digest, strict_json, validate_job_input
from .mos_contract import MODEL as MOS_MODEL

ROOT = Path(__file__).resolve().parents[3]

async def run_solver(value, timeout=120, process_profile=None):
    payload = validate_job_input(value)
    if payload.get("dopingMode") in ("suprem", "suprem-mesh") and process_profile is None:
        raise ValueError("suprem-not-configured")
    if payload.get("dopingMode")=="suprem-mesh" and "deviceMesh" not in process_profile:
        raise ValueError("suprem-contacts-not-configured")
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    environment.update(PYTHONUTF8="1", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    if sys.platform == "win32":
        environment["OPENTCAD_CONTROLLED_CHILD"] = "1"
    if sys.platform.startswith("linux"):
        # A separately installed CPython may need its own shared libpython.
        # Do not inherit arbitrary LD_LIBRARY_PATH from request or shell input.
        environment["LD_LIBRARY_PATH"] = str(Path(sys.base_prefix) / "lib")
    launch = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, "-s", "-m", "backend.app.experimental.solver",
        cwd=ROOT, env=environment, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    ))
    try:
        process = await asyncio.shield(launch)
    except asyncio.CancelledError:
        # Cancellation during process creation must not orphan the native child.
        process = await launch
        process.stdin.close()
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    child_job = None
    async def communicate():
        nonlocal child_job
        if sys.platform == "win32":
            # The real worker announces itself before reading input. A venv
            # launcher PID alone does not identify the process doing the solve.
            import re
            ready = await process.stdout.readline()
            match = re.fullmatch(rb"OPENTCAD_READY_PID=([1-9][0-9]{0,9})\r?\n", ready)
            if match is None:
                raise RuntimeError("solver-startup-protocol")
            from .windows_job import ChildJob
            child_job = ChildJob(int(match[1]))
        process.stdin.write(canonical({"input":payload,"processProfile":process_profile}) if payload.get("dopingMode") in ("suprem","suprem-mesh") else canonical(payload))
        await process.stdin.drain()
        process.stdin.close()
        chunks, size = [], 0
        while chunk := await process.stdout.read(65536):
            size += len(chunk)
            if size > 2_097_152:
                raise RuntimeError("solver-output-limit")
            chunks.append(chunk)
        await process.wait()
        if process.returncode:
            raise RuntimeError("solver-failed")
        lines = b"".join(chunks).splitlines()
        encoded = [line[len(b"OPENTCAD_RESULT="):] for line in lines if line.startswith(b"OPENTCAD_RESULT=")]
        if len(encoded) != 1:
            raise RuntimeError("solver-protocol")
        result = json.loads(encoded[0])
        result_hash = result.pop("resultSha256")
        if digest(result) != result_hash or result["inputSha256"] != digest(payload) or result["input"] != payload or result["productApproved"] is not False:
            raise RuntimeError("solver-integrity")
        result["resultSha256"] = result_hash
        return result
    try:
        return await asyncio.wait_for(communicate(), timeout)
    finally:
        process.stdin.close()
        try:
            if child_job is not None:
                child_job.close()
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

def job_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("job-id")
    return value

class LaboratoryApi(LocalBrokerApi):
    """Explicit separate application; never invokes LocalBrokerApi's M3 routes.

    Reuses the HTTP server's loopback/Host/Origin/Bearer/size checks. Only one
    child process may run. Optional MVP history is not M3 durable authority.
    """
    def __init__(self, runner=run_solver, process_profile=None, store=None):
        self.store = store
        self.storage_failed = False
        self.jobs = store.load(recover=True) if store else {}
        self.tasks = {}
        self.runner = runner
        self.process_profile = process_profile

    def _persist(self, record):
        if self.store is not None:
            try:
                self.store.save(record)
            except Exception:
                self.storage_failed = True
                record.pop("result", None)
                record.update(state="failed", error="history-write-failed")
                return False
        return True

    async def _run(self, identifier, inputs):
        record = self.jobs[identifier]
        try:
            result = await self.runner(inputs, process_profile=self.process_profile) if inputs.get("dopingMode") in ("suprem","suprem-mesh") else await self.runner(inputs)
            record.update(state="complete", result=result)
        except asyncio.CancelledError:
            record.update(state="cancelled")
        except Exception:
            record.update(state="failed", error="solver-failed")
        finally:
            self._persist(record)

    async def handle(self, method, path, body):
        try:
            if method == "GET" and path == "/v1/lab/status":
                return 200, {"schemaVersion": 1, "mode": "experimental", "model": MODEL, "models":[MODEL,MOS_MODEL], "supremProfileSha256":self.process_profile["sourceSha256"] if self.process_profile else None, "supremMeshSha256":self.process_profile.get("deviceMesh",{}).get("meshSha256") if self.process_profile else None, "productEnabled": False}
            if method == "POST" and path == "/v1/lab/jobs":
                if self.storage_failed:
                    return 503, {"error":"history-unavailable"}
                value = strict_json(body)
                if not isinstance(value, dict) or set(value) != {"requestId", "input"}:
                    raise ValueError("request-shape")
                identifier, inputs = job_id(value["requestId"]), validate_job_input(value["input"])
                if inputs.get("dopingMode") in ("suprem","suprem-mesh") and self.process_profile is None:
                    return 409, {"error":"suprem-not-configured"}
                if inputs.get("dopingMode")=="suprem-mesh" and "deviceMesh" not in self.process_profile:
                    return 409, {"error":"suprem-contacts-not-configured"}
                if identifier in self.jobs:
                    if self.jobs[identifier]["inputSha256"] != digest(inputs):
                        return 409, {"error": "request-conflict"}
                    return 200, self.jobs[identifier]
                if any(not task.done() for task in self.tasks.values()):
                    return 409, {"error": "solver-busy"}
                if len(self.jobs) >= 32:
                    return 409, {"error": "session-full"}
                self.jobs[identifier] = {"requestId": identifier, "inputSha256": digest(inputs), "state": "running"}
                if not self._persist(self.jobs[identifier]):
                    return 503, {"error":"history-unavailable"}
                self.tasks[identifier] = asyncio.create_task(self._run(identifier, inputs))
                return 200, self.jobs[identifier]
            if method == "GET" and path == "/v1/lab/jobs":
                return 200, {"jobs":[{k:v for k,v in record.items() if k!="result"} for record in self.jobs.values()]}
            parts = path.split("/")
            if len(parts) in {5, 6} and parts[1:4] == ["v1", "lab", "jobs"]:
                identifier = job_id(parts[4])
                if identifier not in self.jobs:
                    return 404, {"error": "job-not-found"}
                if method == "GET" and len(parts) == 5:
                    return 200, self.jobs[identifier]
                if method == "POST" and len(parts) == 6 and parts[5] == "cancel":
                    if strict_json(body) != {}:
                        raise ValueError("cancel-body")
                    task = self.tasks.get(identifier)
                    if task is not None and not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        # Includes cancellation before the coroutine's first instruction.
                        if self.jobs[identifier]["state"] == "running":
                            self.jobs[identifier].update(state="cancelled")
                        self._persist(self.jobs[identifier])
                    return 200, self.jobs[identifier]
            return 404, {"error": "route-not-found"}
        except (ValueError, TypeError, KeyError, RecursionError):
            return 400, {"error": "request-invalid"}

    async def close(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        for record in self.jobs.values():
            if record["state"] == "running":
                record.update(state="cancelled")
                self._persist(record)

async def serve(args, store=None):
    if importlib.metadata.version("devsim") != "2.11.0":
        raise RuntimeError("Install experimental/requirements.txt first")
    # Run a real solve before claiming the service is ready. No mock fallback.
    from .contract import DEFAULT
    await run_solver({**DEFAULT, "voltageV": 0, "intervals": 100})
    from .suprem import read_structure
    profile = read_structure(args.suprem_structure) if args.suprem_structure else None
    if args.suprem_contacts:
        if profile is None:raise ValueError("contacts-require-structure")
        from .process_mesh import prepare_mesh,read_contacts
        profile["deviceMesh"]=prepare_mesh(profile,read_contacts(args.suprem_contacts))
    api = LaboratoryApi(process_profile=profile, store=store)
    server = LocalApiServer(api, secrets.token_bytes(32), LocalApiBind("127.0.0.1", args.port),
                            static_assets=LocalStaticAssets(args.assets), maximum_body_bytes=8192,
                            maximum_connections=8, request_timeout_seconds=10)
    event = await _stop_event()
    await server.start()
    try:
        print("Experimental DEVSIM laboratory. M3 product remains disabled.", flush=True)
        print(server.browser_url.replace("#local=", "#experiment="), flush=True)
        await event.wait()
    finally:
        await server.close()
        await api.close()

def main():
    parser = argparse.ArgumentParser(description="Opt-in fixed-template DEVSIM laboratory (not an M3 product release)")
    parser.add_argument("--enable-experimental-devsim", action="store_true", required=True)
    parser.add_argument("--assets", type=Path, default=ROOT / "frontend" / "dist")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--suprem-structure", type=Path, help="Read-only SUPREM B.9305 2D structure snapshot; never executes uploaded code")
    parser.add_argument("--suprem-contacts",type=Path,help="Hash-bound explicit exterior edges for source/drain/body/gate")
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    except Exception:
        print("Laboratory startup failed. Install the pinned dependencies, run the solver tests and build the frontend.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
