# Local OpenTCAD MCP

[한국어](../ko/mcp.md) · [Windows local service](windows-mvp.md)

This implemented stdio bridge connects an MCP client to the already running,
authenticated local laboratory. It neither bundles nor starts a solver at startup,
opens a public port, or grants M3 approval. Protocol versions 2025-11-25 and
2025-06-18 are supported. No third-party MCP SDK is required by this implementation.

## Connect

1. Install the pinned local solver environment, build the frontend and run
   `npm run local:mvp -- serve` on Windows (or the experimental `local:lab` command).
2. From the service's private URL, put the port into `OPENTCAD_MCP_PORT` and the
   value after `#experiment=` into `OPENTCAD_MCP_TOKEN` in your MCP client's private
   environment configuration. The host is always numeric `127.0.0.1`.
3. Configure a stdio server with the following conceptual configuration, replacing
   the paths and private values. Client-specific configuration syntax may differ.

```json
{
  "command": "C:/absolute/path/to/node.exe",
  "args": ["C:/absolute/path/to/OpenTCAD/tools/run-mcp.mjs"],
  "env": {
    "OPENTCAD_MCP_PORT": "LOCAL_SERVICE_PORT",
    "OPENTCAD_MCP_TOKEN": "PRIVATE_CURRENT_SESSION_TOKEN"
  }
}
```

Use the equivalent Node and repository paths on other systems. The launcher uses
the repository's `.venv-mvp`; `OPENTCAD_LAB_PYTHON` can select an explicitly trusted
local interpreter. Do not use `npm run` as the MCP client's command: npm banners
would pollute the JSON-RPC stdout stream. Keep credentials out of committed files,
prompts, screenshots and shared logs. Restarting the service changes its port/token;
update the private client configuration and restart the bridge. Never send this
token to a hosted model or remote service as a tool argument.

## Tools and authorization

| Tool | Default | Effect |
|---|---|---|
| `opentcad_capabilities` | Read-only | Local status, models, defaults, input schemas and limits |
| `opentcad_list_jobs` | Read-only | Up to 32 retained job summaries |
| `opentcad_get_job` | Read-only | Job state and verified result hashes, inputs and provenance |
| `opentcad_plan_sweep` | Read-only | Validate up to 8 numerical input variants, without execution |
| `opentcad_submit_job` | Disabled | Submit one supported PN or MOS fixed template |
| `opentcad_cancel_job` | Disabled | Cancel an explicitly identified job |

Add `--allow-execution` after the launcher path only when you authorize a trusted
client to submit/cancel jobs. Keep client-side approval prompts enabled for these
tools; tool annotations alone are not access controls. Cancellation can affect
a job started in the UI. The server still enforces one active solve, input limits,
timeouts, authentication and the configured process profile. It accepts no shell,
Python source, process deck, URL or arbitrary filesystem path as a tool argument.

For SUPREM coupling, first configure the local service with its existing explicit
structure/contact CLI options. MCP does not execute SUPREM process decks. Mesh
geometry and imported doping restrictions also apply to sweep plans.

Sweep plans return deterministic request IDs and normalized inputs. Submit one
point, poll it to completion, then decide whether to submit the next. Repeating a
plan reuses the IDs and can retrieve already completed runs. It is **not an
automatic sweep queue**. To intentionally recompute, use a new UUID. If transport
fails, query the original request ID before retrying; a lost response does not
mean admission failed. Closing the MCP client does not cancel retained jobs.

Results may contain large arrays and unpublished research inputs. The MCP client
may send tool results to its configured AI provider: choose an appropriate client
and data-sharing policy. The bridge itself connects only to the local service and
never sends credentials or results directly to an AI provider.

## Validation and limits

Protocol, read-only authority, malformed inputs, frame bounds, real stdio transport,
authenticated HTTP, cancellation and opt-in native DEVSIM tests are included.
`npm run test:mvp:solver` includes the native MCP path. This is an initial local
MCP implementation, not a hosted Streamable HTTP endpoint, arbitrary-code agent,
automatic optimizer, general process editor or independent numerical qualification.

Protocol references: [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[initialization](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
[tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
