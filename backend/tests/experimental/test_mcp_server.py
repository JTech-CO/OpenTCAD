import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import unittest
from uuid import uuid4

from backend.app.experimental.contract import DEFAULT, MODEL, canonical, digest
from backend.app.experimental.mcp_server import Bridge, LoopbackClient, MAX_MESSAGE, serve_stdio
from backend.app.experimental.service import LaboratoryApi
from backend.app.service.local_api import LocalApiBind, LocalApiServer


class FakeClient:
    def __init__(self): self.calls = []
    def request(self, method, path, value=None):
        self.calls.append((method,path,value))
        if path.endswith("status"): return {"mode":"experimental","productEnabled":False}
        if method == "GET" and path.endswith("jobs"): return {"jobs":[]}
        return {"requestId":value["requestId"],"inputSha256":digest(value["input"]),"state":"running"}


def initialize(bridge):
    response = bridge.handle({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"test","version":"1"}}})
    bridge.handle({"jsonrpc":"2.0","method":"notifications/initialized"})
    return response


def call(bridge, name, arguments=None):
    return bridge.handle({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":name,"arguments":arguments or {}}})


class ProtocolTests(unittest.TestCase):
    def test_initialization_read_only_and_notifications_cannot_execute(self):
        client = FakeClient(); bridge = Bridge(client)
        self.assertIn("error",call(bridge,"opentcad_list_jobs"))
        self.assertEqual(initialize(bridge)["result"]["protocolVersion"],"2025-11-25")
        names = [row["name"] for row in bridge.handle({"jsonrpc":"2.0","id":3,"method":"tools/list"})["result"]["tools"]]
        self.assertNotIn("opentcad_submit_job",names)
        self.assertTrue(call(bridge,"opentcad_submit_job",{"requestId":str(uuid4()),"input":DEFAULT})["result"]["isError"])
        bridge.handle({"jsonrpc":"2.0","method":"tools/call","params":{"name":"opentcad_submit_job"}})
        self.assertEqual(client.calls,[])
        self.assertFalse(call(bridge,"opentcad_capabilities")["result"]["isError"])
        self.assertFalse(call(bridge,"opentcad_list_jobs")["result"]["isError"])

    def test_explicit_execution_is_validated_and_uses_exact_id(self):
        client = FakeClient(); bridge = Bridge(client,True); initialize(bridge)
        identifier = str(uuid4())
        self.assertFalse(call(bridge,"opentcad_submit_job",{"requestId":identifier,"input":DEFAULT})["result"]["isError"])
        self.assertEqual(client.calls[0][2]["requestId"],identifier)
        for arguments in [{"requestId":"../../secrets","input":DEFAULT}, {"requestId":identifier,"input":dict(DEFAULT,script="code")}, {"requestId":identifier,"input":dict(DEFAULT,voltageV=True)}]:
            self.assertTrue(call(bridge,"opentcad_submit_job",arguments)["result"]["isError"])
        self.assertEqual(len(client.calls),1)

    def test_sweep_is_bounded_validated_deterministic_and_never_runs(self):
        client = FakeClient(); bridge = Bridge(client); initialize(bridge)
        args = {"input":DEFAULT,"parameter":"voltageV","values":[0,.1,.2]}
        first = call(bridge,"opentcad_plan_sweep",args)["result"]["structuredContent"]
        self.assertFalse(first["executed"])
        self.assertEqual(len(first["jobs"]),3)
        self.assertEqual(first,call(bridge,"opentcad_plan_sweep",args)["result"]["structuredContent"])
        for changed in [dict(args,values=[0]*9),dict(args,values=[.6]),dict(args,parameter="script")]:
            self.assertTrue(call(bridge,"opentcad_plan_sweep",changed)["result"]["isError"])
        self.assertEqual(client.calls,[])

    def test_stdio_frames_parse_errors_bounds_and_no_secret_output(self):
        bridge = Bridge(FakeClient())
        output = io.BytesIO()
        serve_stdio(bridge,io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n{"x":1,"x":2}\n'),output)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["result"],{})
        self.assertEqual(lines[1]["error"]["code"],-32700)
        output = io.BytesIO(); serve_stdio(bridge,io.BytesIO(b"x"*(MAX_MESSAGE+1)+b"\n"),output)
        self.assertEqual(len(output.getvalue().splitlines()),1)
        for invalid in [[], {"jsonrpc":"2.0","id":True,"method":"ping"}]:
            self.assertEqual(bridge.handle(invalid)["error"]["code"],-32600)

    def test_real_stdio_process_has_only_json_rpc_stdout(self):
        request = canonical({"jsonrpc":"2.0","id":1,"method":"ping"})+b"\n"
        environment = dict(os.environ,OPENTCAD_MCP_PORT="1",OPENTCAD_MCP_TOKEN="A"*43)
        process = subprocess.run([sys.executable,"-m","backend.app.experimental.mcp_server"],input=request,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=environment,timeout=15)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)["result"],{})
        self.assertNotIn(b"A"*43,process.stdout+process.stderr)

    def test_bad_credentials_cannot_be_used_as_headers(self):
        for port,token in [(0,"A"*43),(65536,"A"*43),(True,"A"*43),(80,"A"*42+"\n")]:
            with self.assertRaises(ValueError): LoopbackClient(port,token)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_http_auth_submit_poll_and_cancel(self):
        async def runner(_): await asyncio.sleep(60)
        api = LaboratoryApi(runner)
        secret = b"m"*32
        server = LocalApiServer(api,secret,LocalApiBind(),maximum_body_bytes=8192)
        await server.start()
        bridge = Bridge(LoopbackClient(server.port,base64.urlsafe_b64encode(secret).rstrip(b"=").decode()),True)
        initialize(bridge)
        identifier = str(uuid4())
        try:
            self.assertFalse((await asyncio.to_thread(call,bridge,"opentcad_capabilities"))["result"]["isError"])
            submitted = await asyncio.to_thread(call,bridge,"opentcad_submit_job",{"requestId":identifier,"input":DEFAULT})
            self.assertEqual(submitted["result"]["structuredContent"]["state"],"running")
            queried = await asyncio.to_thread(call,bridge,"opentcad_get_job",{"requestId":identifier})
            self.assertEqual(queried["result"]["structuredContent"]["state"],"running")
            cancelled = await asyncio.to_thread(call,bridge,"opentcad_cancel_job",{"requestId":identifier})
            self.assertEqual(cancelled["result"]["structuredContent"]["state"],"cancelled")
            unauthorized = Bridge(LoopbackClient(server.port,"A"*43)); initialize(unauthorized)
            self.assertTrue((await asyncio.to_thread(call,unauthorized,"opentcad_capabilities"))["result"]["isError"])
        finally:
            await server.close(); await api.close()

    @unittest.skipUnless(os.environ.get("OPENTCAD_TEST_DEVSIM") == "1", "user-installed DEVSIM")
    async def test_native_solver_result_through_mcp_http_bridge(self):
        api = LaboratoryApi()
        secret = b"n"*32
        server = LocalApiServer(api,secret,LocalApiBind(),maximum_body_bytes=8192)
        await server.start()
        bridge = Bridge(LoopbackClient(server.port,base64.urlsafe_b64encode(secret).rstrip(b"=").decode()),True)
        initialize(bridge)
        identifier = str(uuid4())
        async def wire_call(name, arguments):
            messages = [
                {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"acceptance","version":"1"}}},
                {"jsonrpc":"2.0","method":"notifications/initialized"},
                {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":name,"arguments":arguments}},
            ]
            environment = dict(os.environ,OPENTCAD_MCP_PORT=str(server.port),OPENTCAD_MCP_TOKEN=bridge.client.token)
            process = await asyncio.create_subprocess_exec(sys.executable,"-m","backend.app.experimental.mcp_server","--allow-execution",stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=environment)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(b"".join(canonical(message)+b"\n" for message in messages)),20)
                self.assertEqual(process.returncode,0,stderr)
                self.assertNotIn(bridge.client.token.encode(),stdout+stderr)
                responses = [json.loads(line) for line in stdout.splitlines()]
                self.assertEqual(len(responses),2)
                return responses[-1]
            finally:
                if process.returncode is None:
                    process.kill(); await process.wait()
        try:
            response = await wire_call("opentcad_submit_job",{"requestId":identifier,"input":dict(DEFAULT,voltageV=.1,intervals=100)})
            self.assertFalse(response["result"]["isError"])
            await asyncio.wait_for(api.tasks[identifier],120)
            result = await wire_call("opentcad_get_job",{"requestId":identifier})
            self.assertFalse(result["result"]["isError"])
            record = result["result"]["structuredContent"]
            self.assertEqual(record["state"],"complete")
            self.assertEqual(record["result"]["model"],MODEL)
            self.assertGreater(record["result"]["iv"][-1][1],0)
        finally:
            await server.close(); await api.close()
