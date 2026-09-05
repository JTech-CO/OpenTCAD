import asyncio
import json
import unittest
from uuid import uuid4

from backend.app.experimental.contract import DEFAULT, canonical, strict_json, validate_input
from backend.app.experimental.service import LaboratoryApi
from backend.app.service.local_api import LocalApiBind, LocalApiServer

class InputTests(unittest.TestCase):
    def test_rejects_nonfinite_unknown_code_mesh_and_duplicates(self):
        for value in [{**DEFAULT, "script": "print(1)"}, {**DEFAULT, "voltageV": float("nan")},
                      {**DEFAULT, "intervals": 200.0}, {**DEFAULT, "areaUm2": True}, {**DEFAULT, "lengthUm": 0}]:
            with self.assertRaises(ValueError):
                validate_input(value)
        for source in [b'{"x":1,"x":2}', b'{"a":NaN}', b'{"constructor":1}', b' ' * 8193]:
            with self.assertRaises(ValueError):
                strict_json(source)

class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.event = asyncio.Event()
        self.calls = 0
        async def runner(value):
            self.calls += 1
            await self.event.wait()
            return {"numerical": True}
        self.api = LaboratoryApi(runner)

    async def asyncTearDown(self):
        await self.api.close()

    async def submit(self, identifier=None, value=None):
        return await self.api.handle("POST", "/v1/lab/jobs", canonical({"requestId": identifier or str(uuid4()), "input": value or DEFAULT}))

    async def test_admission_idempotence_conflict_and_cancellation(self):
        identifier = str(uuid4())
        self.assertEqual((await self.submit(identifier))[0], 200)
        await asyncio.sleep(0)
        self.assertEqual((await self.submit(identifier))[0], 200)
        self.assertEqual(self.calls, 1)
        self.assertEqual((await self.submit())[0], 409)
        self.assertEqual((await self.submit(identifier, {**DEFAULT, "voltageV": .3}))[0], 409)
        path = f"/v1/lab/jobs/{identifier}/cancel"
        self.assertEqual((await self.api.handle("POST", path, b"{}"))[1]["state"], "cancelled")
        self.assertEqual((await self.api.handle("POST", path, b"{}"))[1]["state"], "cancelled")
        self.event.set()
        await asyncio.sleep(0)
        self.assertNotIn("result", self.api.jobs[identifier])

    async def test_cancel_before_first_instruction_and_no_m3_routes(self):
        identifier = str(uuid4())
        await self.submit(identifier)
        status, result = await self.api.handle("POST", f"/v1/lab/jobs/{identifier}/cancel", b"{}")
        self.assertEqual((status, result["state"]), (200, "cancelled"))
        self.assertEqual((await self.api.handle("POST", "/v1/jobs", b"{}"))[0], 404)
        self.assertFalse((await self.api.handle("GET", "/v1/lab/status", b""))[1]["productEnabled"])

    async def test_failures_are_redacted_and_history_bounded(self):
        async def fail(_):
            raise RuntimeError("private path")
        self.api.runner = fail
        for _ in range(32):
            _, record = await self.submit()
            await asyncio.sleep(0)
            self.assertEqual(record["state"], "failed")
            self.assertNotIn("private", json.dumps(record))
        self.assertEqual((await self.submit())[0], 409)

    async def test_http_auth_origin_bounds_and_real_dispatch(self):
        secret = b"x" * 32
        server = LocalApiServer(self.api, secret, LocalApiBind(), maximum_body_bytes=8192)
        await server.start()
        import base64
        bearer = base64.urlsafe_b64encode(secret).rstrip(b"=").decode()
        async def request(auth=True, origin=None, body=None):
            reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
            path = "/v1/lab/status" if body is None else "/v1/lab/jobs"
            headers = [f'{"GET" if body is None else "POST"} {path} HTTP/1.1', f"Host: 127.0.0.1:{server.port}"]
            if auth:
                headers.append(f"Authorization: Bearer {bearer}")
            if origin:
                headers.append(f"Origin: {origin}")
            if body is not None:
                headers.extend(["Content-Type: application/json", f"Content-Length: {len(body)}"])
            writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + (body or b""))
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            return response
        try:
            self.assertIn(b"200 OK", await request())
            self.assertIn(b"401 Unauthorized", await request(auth=False))
            self.assertIn(b"403 Forbidden", await request(origin="https://example.com"))
            self.assertIn(b"413 Content Too Large", await request(body=b" " * 8193))
            self.assertIn(b"200 OK", await request(body=canonical({"requestId": str(uuid4()), "input": DEFAULT})))
        finally:
            await server.close()
