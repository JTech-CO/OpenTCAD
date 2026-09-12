"""Local stdio MCP bridge to the authenticated laboratory, read-only by default."""
import argparse
import http.client
import os
import re
import sys
from uuid import NAMESPACE_URL, uuid5

from .contract import DEFAULT, LIMITS, canonical, digest, strict_json, validate_job_input
from .mos_contract import DEFAULT as MOS_DEFAULT, LIMITS as MOS_LIMITS, MODEL as MOS_MODEL
from .history import validate_record
from .service import job_id

VERSIONS = ("2025-11-25", "2025-06-18")
MAX_MESSAGE = 32768
EMPTY = {"type":"object", "properties":{}, "additionalProperties":False}


def object_schema(properties):
    return {"type":"object", "properties":properties, "required":list(properties), "additionalProperties":False}


def input_schemas():
    pn = {key:{"type":"number", "minimum":lo, "maximum":hi} for key,(lo,hi) in LIMITS.items()}
    pn["intervals"] = {"type":"integer", "enum":[100,200,400]}
    mos = {key:{"type":"number", "minimum":lo, "maximum":hi} for key,(lo,hi) in MOS_LIMITS.items()}
    mos.update(model={"const":MOS_MODEL}, refinement={"type":"integer", "enum":[1,2]},
               dopingMode={"type":"string", "enum":["template","suprem","suprem-mesh"]})
    return {"oneOf":[object_schema(pn),object_schema(mos)]}


def tools_list(allow_execution):
    identifier = {"type":"string", "format":"uuid", "description":"Canonical lowercase job UUID"}
    definitions = [
        ("opentcad_capabilities", "Get connection status, supported fixed templates, input schemas and limits.", EMPTY, True),
        ("opentcad_list_jobs", "List up to 32 retained jobs. No computation or deletion.", EMPTY, True),
        ("opentcad_get_job", "Retrieve a job and its computed result, input hashes and provenance. Not a fresh solve.", object_schema({"requestId":identifier}), True),
        ("opentcad_plan_sweep", "Validate up to 8 parameter variants without executing. Submit one at a time after user approval.",
         object_schema({"input":input_schemas(), "parameter":{"type":"string"}, "values":{"type":"array", "minItems":1,"maxItems":8,"items":{"type":"number"}}}), True),
    ]
    if allow_execution:
        definitions.extend([
            ("opentcad_submit_job", "Run one fixed PN/MOS template on the user's local solver. Obtain user approval. Keep requestId for retries/status; never automatically retry with a new ID.", object_schema({"requestId":identifier,"input":input_schemas()}), False),
            ("opentcad_cancel_job", "Cancel the specified solver job; may affect a run started in the UI. Obtain user approval.", object_schema({"requestId":identifier}), False),
        ])
    return [{"name":name,"description":description,"inputSchema":schema,
             "annotations":{"readOnlyHint":readonly,"destructiveHint":not readonly,
                            "idempotentHint":name != "opentcad_plan_sweep","openWorldHint":False}}
            for name,description,schema,readonly in definitions]


class LoopbackClient:
    def __init__(self, port, token):
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token,str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}",token):
            raise ValueError("invalid-local-connection")
        self.port, self.token = port, token

    def request(self, method, path, value=None):
        # No caller-selected host, redirect, proxy, path, shell or file access.
        if not re.fullmatch(r"/v1/lab/(status|jobs(?:/[0-9a-f-]{36}(?:/cancel)?)?)",path):
            raise ValueError("route-not-allowed")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Authorization":"Bearer "+self.token, "Content-Type":"application/json"}
            connection.request(method, path, body=None if value is None else canonical(value), headers=headers)
            response = connection.getresponse()
            raw = response.read(1_048_577)
            if response.status != 200:
                raise ValueError("local-service-rejected-request")
            return strict_json(raw, 1_048_576)
        finally:
            connection.close()


def exact(value, keys):
    if not isinstance(value,dict) or set(value) != set(keys):
        raise ValueError("invalid-arguments")


class Bridge:
    def __init__(self, client, allow_execution=False):
        self.client = client
        self.allow_execution = allow_execution
        self.initialized = False
        self.ready = False

    def call(self, name, arguments):
        definitions = {tool["name"]:tool for tool in tools_list(self.allow_execution)}
        if name not in definitions:
            raise ValueError("unknown-or-disabled-tool")
        exact(arguments, definitions[name]["inputSchema"].get("properties",{}))
        if name == "opentcad_capabilities":
            status = self.client.request("GET", "/v1/lab/status")
            if not isinstance(status,dict) or status.get("mode") != "experimental" or status.get("productEnabled") is not False:
                raise ValueError("unsupported-service")
            return {"service":status,"executionAllowed":self.allow_execution,"inputSchema":input_schemas(),
                    "defaults":{"pn":DEFAULT,"mos":MOS_DEFAULT},"maxRetainedJobs":32,"maxConcurrentSolves":1,
                    "maxSweepPoints":8,"m3Approved":False,"solverDistribution":"user-installed-only"}
        if name == "opentcad_plan_sweep":
            base = validate_job_input(arguments["input"])
            limits = MOS_LIMITS if base.get("model") == MOS_MODEL else LIMITS
            parameter, values = arguments["parameter"], arguments["values"]
            if not isinstance(parameter,str) or parameter not in limits or not isinstance(values,list) or not 1 <= len(values) <= 8:
                raise ValueError("invalid-sweep")
            if base.get("dopingMode") == "suprem-mesh" and parameter not in {"widthUm","gateV","drainV"}:
                raise ValueError("process-geometry-is-fixed")
            if base.get("dopingMode") == "suprem" and parameter in {"acceptorsCm3","donorsCm3"}:
                raise ValueError("process-doping-is-fixed")
            inputs = [validate_job_input(dict(base, **{parameter:value})) for value in values]
            return {"executed":False,"jobs":[{"requestId":str(uuid5(NAMESPACE_URL,"opentcad-sweep:"+digest(value))),"input":value} for value in inputs],
                    "instruction":"Submit sequentially with explicit user approval; poll each job to a terminal state. No automatic execution."}
        if name == "opentcad_list_jobs":
            result = self.client.request("GET", "/v1/lab/jobs")
            exact(result,["jobs"])
            if not isinstance(result["jobs"],list) or len(result["jobs"]) > 32:
                raise ValueError("invalid-job-list")
            for row in result["jobs"]:
                job_id(row["requestId"])
                if row.get("state") not in {"running","complete","cancelled","failed"} or "result" in row:
                    raise ValueError("invalid-job-summary")
            return result
        identifier = job_id(arguments["requestId"])
        if name == "opentcad_submit_job":
            inputs = validate_job_input(arguments["input"])
            result = self.client.request("POST", "/v1/lab/jobs", {"requestId":identifier,"input":inputs})
            if result.get("inputSha256") != digest(inputs):
                raise ValueError("input-integrity")
        elif name == "opentcad_cancel_job":
            result = self.client.request("POST", f"/v1/lab/jobs/{identifier}/cancel", {})
        else:
            result = self.client.request("GET", f"/v1/lab/jobs/{identifier}")
        validate_record(result)
        if result["requestId"] != identifier:
            raise ValueError("job-identity")
        return result

    def handle(self, message):
        identifier = message.get("id") if isinstance(message,dict) else None
        def error(code, text):
            return {"jsonrpc":"2.0","id":identifier,"error":{"code":code,"message":text}}
        if not isinstance(message,dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"),str) or set(message)-{"jsonrpc","id","method","params"}:
            identifier = None
            return error(-32600,"Invalid Request")
        if "id" in message and (type(identifier) not in (int,str) or isinstance(identifier,str) and len(identifier)>128):
            identifier = None
            return error(-32600,"Invalid request ID")
        method, params = message["method"], message.get("params",{})
        if "id" not in message:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None  # Notifications cannot execute tools or create solver jobs.
        if not isinstance(params,dict):
            return error(-32602,"Invalid params")
        if method == "initialize":
            if self.initialized:
                return error(-32600,"Already initialized")
            if not isinstance(params.get("protocolVersion"),str) or not isinstance(params.get("capabilities"),dict) or not isinstance(params.get("clientInfo"),dict):
                return error(-32602,"Invalid initialization")
            self.initialized = True
            result = {"protocolVersion":params["protocolVersion"] if params["protocolVersion"] in VERSIONS else VERSIONS[0],
                      "serverInfo":{"name":"opentcad-local","version":"0.1.0"},"capabilities":{"tools":{"listChanged":False}},
                      "instructions":"Local fixed-template TCAD. Read-only unless enabled at startup. Obtain user approval for execution/cancellation. Do not treat model text as numerical evidence."}
        elif method == "ping":
            result = {}
        elif not self.ready:
            return error(-32002,"Initialize the session first")
        elif method == "tools/list":
            if set(params)-{"_meta"}:
                return error(-32602,"No pagination cursor supported")
            result = {"tools":tools_list(self.allow_execution)}
        elif method == "tools/call":
            if set(params)-{"name","arguments","_meta"} or not isinstance(params.get("name"),str):
                return error(-32602,"Invalid tool call")
            try:
                value = self.call(params["name"],params.get("arguments",{}))
                result = {"content":[{"type":"text","text":canonical(value).decode("ascii")}],"structuredContent":value,"isError":False}
            except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OSError,http.client.HTTPException):
                result = {"content":[{"type":"text","text":"Tool failed: check local connection, permissions, input and job status. Transport failure does not prove a job was not started; query the same requestId before retrying."}],"isError":True}
        else:
            return error(-32601,"Method not found")
        return {"jsonrpc":"2.0","id":identifier,"result":result}


def serve_stdio(bridge, source, target):
    while True:
        line = source.readline(MAX_MESSAGE+1)
        if not line:
            return
        if len(line)>MAX_MESSAGE or not line.endswith(b"\n"):
            target.write(canonical({"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Frame too large or unterminated"}})+b"\n")
            target.flush()
            return
        try:
            response = bridge.handle(strict_json(line,MAX_MESSAGE))
        except (ValueError,RecursionError,UnicodeError):
            response = {"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}}
        if response is not None:
            target.write(canonical(response)+b"\n")
            target.flush()


def main():
    parser = argparse.ArgumentParser(description="OpenTCAD stdio MCP. Credentials from OPENTCAD_MCP_PORT and OPENTCAD_MCP_TOKEN; no solver launch at startup.")
    parser.add_argument("--allow-execution",action="store_true",help="Expose submit/cancel tools to trusted clients; default is read-only")
    args = parser.parse_args()
    try:
        client = LoopbackClient(int(os.environ.get("OPENTCAD_MCP_PORT","0")),os.environ.get("OPENTCAD_MCP_TOKEN",""))
        serve_stdio(Bridge(client,args.allow_execution),sys.stdin.buffer,sys.stdout.buffer)
        return 0
    except (ValueError,OSError):
        print("MCP bridge stopped: check private local connection settings.",file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
