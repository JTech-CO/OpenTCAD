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
from .contract import MODEL, canonical, digest, strict_json, validate_input

ROOT = Path(__file__).resolve().parents[3]

async def run_solver(value, timeout=60):
    payload = validate_input(value)
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"}
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    environment.update(PYTHONUTF8="1", PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
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
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    async def communicate():
        process.stdin.write(canonical(payload))
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
    child process may run. History is bounded and session-local, not durable.
    """
    def __init__(self, runner=run_solver):
        self.jobs = {}
        self.tasks = {}
        self.runner = runner

    async def _run(self, identifier, inputs):
        record = self.jobs[identifier]
        try:
            result = await self.runner(inputs)
            record.update(state="complete", result=result)
        except asyncio.CancelledError:
            record.update(state="cancelled")
        except Exception:
            record.update(state="failed", error="solver-failed")

    async def handle(self, method, path, body):
        try:
            if method == "GET" and path == "/v1/lab/status":
                return 200, {"schemaVersion": 1, "mode": "experimental", "model": MODEL, "productEnabled": False}
            if method == "POST" and path == "/v1/lab/jobs":
                value = strict_json(body)
                if not isinstance(value, dict) or set(value) != {"requestId", "input"}:
                    raise ValueError("request-shape")
                identifier, inputs = job_id(value["requestId"]), validate_input(value["input"])
                if identifier in self.jobs:
                    if self.jobs[identifier]["inputSha256"] != digest(inputs):
                        return 409, {"error": "request-conflict"}
                    return 200, self.jobs[identifier]
                if any(not task.done() for task in self.tasks.values()):
                    return 409, {"error": "solver-busy"}
                if len(self.jobs) >= 32:
                    return 409, {"error": "session-full"}
                self.jobs[identifier] = {"requestId": identifier, "inputSha256": digest(inputs), "state": "running"}
                self.tasks[identifier] = asyncio.create_task(self._run(identifier, inputs))
                return 200, self.jobs[identifier]
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
                    task = self.tasks[identifier]
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        # Includes cancellation before the coroutine's first instruction.
                        self.jobs[identifier].update(state="cancelled")
                    return 200, self.jobs[identifier]
            return 404, {"error": "route-not-found"}
        except (ValueError, TypeError, KeyError, RecursionError):
            return 400, {"error": "request-invalid"}

    async def close(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

async def serve(args):
    if importlib.metadata.version("devsim") != "2.11.0":
        raise RuntimeError("Install experimental/requirements.txt first")
    # Run a real solve before claiming the service is ready. No mock fallback.
    from .contract import DEFAULT
    await run_solver({**DEFAULT, "voltageV": 0, "intervals": 100})
    api = LaboratoryApi()
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
