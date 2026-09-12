"""Opt-in real DEVSIM checks. No mocked solve can satisfy this suite."""
import asyncio
import math
import os
import unittest
import base64
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from backend.app.experimental.contract import DEFAULT
from backend.app.experimental.service import run_solver
from backend.app.experimental.service import LaboratoryApi
from backend.app.experimental.replay import compare, read_record
from backend.app.service.local_api import LocalApiServer, LocalApiBind

@unittest.skipUnless(os.environ.get("OPENTCAD_TEST_DEVSIM") == "1", "requires explicitly installed DEVSIM 2.11.0")
class NumericalTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeatability_mesh_refinement_and_parameter_response(self):
        coarse = await run_solver({**DEFAULT, "intervals": 100})
        normal = await run_solver(DEFAULT)
        fine = await run_solver({**DEFAULT, "intervals": 400})
        again = await run_solver(DEFAULT)
        if normal["resultSha256"] != again["resultSha256"]:
            from backend.app.experimental.repeatability import capture_failure
            try:
                evidence = capture_failure(normal, again)
                print(f"PN repeat mismatch evidence preserved: {evidence}", flush=True)
            except Exception:
                print("PN repeat mismatch evidence could not be saved; original equality assertion still applies.", flush=True)
        self.assertEqual(normal["resultSha256"], again["resultSha256"])
        self.assertEqual(normal["iv"], again["iv"])
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / "run.json"
            record.write_text(json.dumps(normal), encoding="utf-8")
            self.assertTrue(compare(read_record(record), again)["numericallyReproduced"])
            tampered = {**normal, "iv": [[0, 1]]}
            record.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_record(record)
        for result in [coarse, normal, fine]:
            self.assertLess(result["checks"]["builtInErrorV"], 1e-7)
            self.assertLessEqual(result["checks"]["maxCurrentToleranceRatio"], 1)
            self.assertLess(abs(result["iv"][0][1]), 1e-14)
            self.assertTrue(all(b[1] > a[1] for a, b in zip(result["iv"], result["iv"][1:])))
            self.assertFalse(result["productApproved"])
        coarse_error = abs(coarse["iv"][-1][1] / fine["iv"][-1][1] - 1)
        fine_error = abs(normal["iv"][-1][1] / fine["iv"][-1][1] - 1)
        self.assertLess(fine_error, .02)
        self.assertLess(fine_error, coarse_error)
        doubled = await run_solver({**DEFAULT, "areaUm2": DEFAULT["areaUm2"] * 2})
        self.assertAlmostEqual(doubled["iv"][-1][1] / normal["iv"][-1][1], 2, places=10)
        self.assertEqual(doubled["potentialV"], normal["potentialV"])
        changed = await run_solver({**DEFAULT, "donorsCm3": 2e16})
        self.assertNotEqual(changed["potentialV"], normal["potentialV"])
        self.assertGreater(changed["checks"]["builtInComputedV"], normal["checks"]["builtInComputedV"])
        print(f"PN benchmark: mesh relative current error={fine_error:.6g}; equilibrium error={normal['checks']['builtInErrorV']:.6g} V; repeat hash identical")

    async def test_timeout_terminates_solver_and_next_run_succeeds(self):
        with self.assertRaises(TimeoutError):
            await run_solver(DEFAULT, timeout=.001)
        self.assertEqual((await run_solver({**DEFAULT, "voltageV": 0}))["solver"], "DEVSIM")

    async def test_reverse_boundary_and_carrier_equilibrium_at_zero_bias(self):
        result = await run_solver({**DEFAULT, "voltageV": 0, "acceptorsCm3": 2e16})
        for n, p in zip(result["electronsCm3"], result["holesCm3"]):
            self.assertTrue(math.isclose(n * p, 1e20, rel_tol=1e-7))

    async def test_actual_http_to_native_solver_to_result_and_cancellation(self):
        api = LaboratoryApi()
        secret = b"x" * 32
        server = LocalApiServer(api, secret, LocalApiBind(), maximum_body_bytes=8192)
        await server.start()
        token = base64.urlsafe_b64encode(secret).rstrip(b"=").decode()
        async def request(path, body=None):
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            encoded = b"" if body is None else json.dumps(body).encode()
            headers = [f'{"GET" if body is None else "POST"} {path} HTTP/1.1',
                       f"Host: 127.0.0.1:{server.port}", f"Origin: http://127.0.0.1:{server.port}", f"Authorization: Bearer {token}"]
            if body is not None:
                headers.extend(["Content-Type: application/json", f"Content-Length: {len(encoded)}"])
            writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + encoded)
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            self.assertIn(b"200 OK", response.split(b"\r\n")[0])
            return json.loads(response.split(b"\r\n\r\n", 1)[1])
        try:
            identifier = str(uuid4())
            await request("/v1/lab/jobs", {"requestId": identifier, "input": DEFAULT})
            for _ in range(120):
                record = await request(f"/v1/lab/jobs/{identifier}")
                if record["state"] != "running":
                    break
                await asyncio.sleep(.05)
            self.assertEqual(record["state"], "complete")
            self.assertEqual(record["result"]["solver"], "DEVSIM")
            self.assertGreater(record["result"]["iv"][-1][1], 0)
            cancelled = str(uuid4())
            await request("/v1/lab/jobs", {"requestId": cancelled, "input": DEFAULT})
            self.assertEqual((await request(f"/v1/lab/jobs/{cancelled}/cancel", {}))["state"], "cancelled")
            self.assertTrue(all(task.done() for task in api.tasks.values()))
        finally:
            await server.close()
            await api.close()
