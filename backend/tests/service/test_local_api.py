from __future__ import annotations

import asyncio
import base64
import json
import unittest
from uuid import uuid4

from backend.app.broker.recovery import RecoveryReport
from backend.app.broker.state_composition import BrokerStartupReport
from backend.app.service.local_api import (
    LocalApiBind,
    LocalApiServer,
    LocalBrokerApi,
)
from backend.app.service.worker import (
    LocalBrokerWorker,
    WorkerEnvelope,
    WorkerOperation,
)


class FakeWorker(LocalBrokerWorker):
    def __init__(self) -> None:
        self.envelopes: list[WorkerEnvelope] = []

    @property
    def started(self) -> bool:
        return True

    async def submit(self, envelope: WorkerEnvelope) -> object:
        self.envelopes.append(envelope)
        if envelope.operation is WorkerOperation.STARTUP_RECOVERY:
            return BrokerStartupReport(
                envelope.payload.startup_id,
                (RecoveryReport(str(uuid4()), (), None),),
            )
        raise AssertionError(envelope.operation)


class LocalApiServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.secret = b"s" * 32
        self.worker = FakeWorker()
        self.server = LocalApiServer(
            LocalBrokerApi(self.worker),
            self.secret,
            LocalApiBind("127.0.0.1", 0),
            maximum_body_bytes=1_048_576,
        )
        await self.server.start()

    async def asyncTearDown(self) -> None:
        await self.server.close()

    @property
    def authorization(self) -> str:
        token = base64.urlsafe_b64encode(self.secret).rstrip(b"=").decode()
        return f"Bearer {token}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        authorization: str | None = None,
        host: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict]:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1",
            self.server.port,
        )
        headers = [
            f"{method} {path} HTTP/1.1",
            f"Host: {host or f'127.0.0.1:{self.server.port}'}",
            "Connection: close",
        ]
        if authorization is not None:
            headers.append(f"Authorization: {authorization}")
        if origin is not None:
            headers.append(f"Origin: {origin}")
        if method == "POST":
            headers.extend([
                "Content-Type: application/json",
                f"Content-Length: {len(body)}",
            ])
        writer.write(("\r\n".join(headers) + "\r\n\r\n").encode() + body)
        await writer.drain()
        raw = await reader.read()
        writer.close()
        await writer.wait_closed()
        head, response_body = raw.split(b"\r\n\r\n", maxsplit=1)
        status = int(head.split(b" ", maxsplit=2)[1])
        return status, json.loads(response_body)

    async def test_auth_host_and_origin_are_enforced(self) -> None:
        status, body = await self.request("GET", "/v1/health")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication-required")

        status, body = await self.request(
            "GET",
            "/v1/health",
            authorization=self.authorization,
            host="attacker.example",
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "host-not-loopback")

        status, body = await self.request(
            "GET",
            "/v1/health",
            authorization=self.authorization,
            origin="https://attacker.example",
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "origin-not-allowed")

        status, body = await self.request(
            "GET",
            "/v1/health",
            authorization=self.authorization,
        )
        self.assertEqual((status, body["status"]), (200, "ready"))

    async def test_startup_route_reaches_typed_worker_transport(self) -> None:
        request_id = str(uuid4())
        startup_id = str(uuid4())
        payload = json.dumps(
            {
                "requestId": request_id,
                "startupId": startup_id,
                "pageLimit": 25,
            },
            separators=(",", ":"),
        ).encode()
        status, body = await self.request(
            "POST",
            "/v1/startup",
            body=payload,
            authorization=self.authorization,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["startup_id"], startup_id)
        self.assertEqual(len(self.worker.envelopes), 1)
        envelope = self.worker.envelopes[0]
        self.assertEqual(envelope.request_id, request_id)
        self.assertEqual(envelope.operation, WorkerOperation.STARTUP_RECOVERY)
        self.assertEqual(envelope.payload.page_limit, 25)

    async def test_duplicate_json_keys_are_rejected(self) -> None:
        payload = b'{"requestId":"x","requestId":"y"}'
        status, body = await self.request(
            "POST",
            "/v1/startup",
            body=payload,
            authorization=self.authorization,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid-json")
        self.assertEqual(self.worker.envelopes, [])

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            LocalApiBind("0.0.0.0", 8080)


if __name__ == "__main__":
    unittest.main()
