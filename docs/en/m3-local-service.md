# M3 local product service

[한국어](../ko/m3-local-service.md)

M3 adds an executable, cross-platform local host around the existing durable
broker contracts. The committed release remains solver-disabled. The local
host is useful today as a same-origin, non-executing product preview, while the
product command stays fail-closed until every M3 gate and one code-owned
release profile are approved together.

## Available commands

Build the static assets before starting either local web host:

```bash
npm install
npm run build
```

Inspect the committed gate manifest without creating local product state:

```bash
npm run local:doctor
```

Start the local blocked preview on an ephemeral loopback port:

```bash
npm run local:preview
```

The command prints one JSON object containing `browserUrl`. Open that URL in
the same user session. Its fragment contains an ephemeral bearer bootstrap, so
do not copy it into logs, issue reports, shell history, or shared messages. The
client removes the bootstrap fragment immediately and keeps the secret in
memory only.

The product command is:

```bash
npm run local:serve
```

With the committed manifest it returns exit code `3` and
`productStarted:false`. This is the expected release state. It checks
activation before loading assets, creating directories, taking an instance
lock, opening a credential store or SQLite database, probing Docker or Podman,
or binding a socket.

## Preview and product boundaries

| Property | Static GitHub Pages | Local blocked preview | Activated product host |
|---|---:|---:|---:|
| Serves the introduction and workspace | Yes | Yes | Yes |
| Opens any local connection automatically | No | No | No |
| Exposes redacted service status | No | Yes | Yes |
| Creates durable application state | No | No | Yes |
| Contacts an OS credential store | No | No | Yes |
| Contacts Docker or Podman | No | No | Yes |
| Can submit solver work | No | No | Only after release activation |

GitHub Pages performs no local-service fetch. On loopback, the user must select
the explicit connection control before the UI reads `/v1/status`. Transport
connection and solver authorization are displayed as separate states.

## Operator configuration

The example is [config/local-service.example.json](../../config/local-service.example.json):

```json
{
  "schemaVersion": 1,
  "runtimeBackend": "docker",
  "apiPort": 0,
  "backupIntervalMs": 86400000,
  "recoveryPageLimit": 100
}
```

The parser accepts exactly these keys, rejects duplicate keys and symbolic
links, and bounds every numeric field. `apiPort:0` selects an ephemeral port.
An operator cannot configure an image, digest, command, entrypoint, mount,
environment variable, credential identifier, database path, or host
executable through this file.

For release builds, copy the example to the platform configuration path:

| Host | Configuration path | State path |
|---|---|---|
| Windows | `%LOCALAPPDATA%\OpenTCAD\config\local-service.json` | `%LOCALAPPDATA%\OpenTCAD\state` |
| macOS | `~/Library/Application Support/OpenTCAD/config/local-service.json` | `~/Library/Application Support/OpenTCAD/state` |
| Linux | `$XDG_CONFIG_HOME/opentcad/local-service.json` or `~/.config/opentcad/local-service.json` | `$XDG_STATE_HOME/opentcad` or `~/.local/state/opentcad` |

Development and qualification may use an explicit absolute data root:

```bash
python -m backend.app.service serve --data-root /absolute/test/root
```

It does not bypass activation.

## Activation and startup order

The release boundary is intentionally code-owned:

1. Load the strict, evidence-hash-bound M3 manifest.
2. Require all eight gates and exact runtime grants.
3. Select a reviewed release profile bound to the manifest SHA-256 and chosen
   backend.
4. Only then prepare per-user paths and acquire the single-instance lock.
5. Probe the approved runtime and require every digest-pinned image to be
   present locally. The service never pulls an image during startup.
6. Provision native credentials, open durable SQLite stores, run recovery, and
   start the scheduler.
7. Bind a numeric `127.0.0.1` address and publish a secret-free endpoint
   record.

`PRODUCT_RELEASE_PROFILES` is empty in the committed source. A manifest edit
alone therefore cannot enable execution.

## Runtime and lifecycle integration

- Docker and Podman calls use a resolved executable, an allowlisted
  environment, shell-free argv, bounded output, and bounded time.
- Runtime objects carry job identity, owner identity, fencing generation,
  entrypoint identity, and output limits as native labels.
- Product operations take a job-specific cross-process lock around durable
  fence verification and native mutation. A takeover cannot interleave with an
  older owner's runtime command.
- Restart cancellation reconstructs the bounded output limit from a validated
  native label. A missing or malformed label fences the operation before the
  native kill command.
- Successful artifact adoption still requires resident validated job metadata;
  the adapter does not guess an expected artifact manifest after a restart.
- Execution, cancellation, recovery, maintenance, authenticated import and
  export, scheduled backups, and shutdown share the same application
  lifecycle.
- The worker bounds total queued and active requests and reserves a control
  lane for cancellation.

## Local HTTP boundary

The local service uses a small standard-library HTTP server rather than a
general external web framework. Static assets and API responses are served
from the same numeric loopback origin. The boundary enforces:

- loopback peer, Host, and Origin checks;
- bearer authentication for API routes;
- strict JSON shapes and duplicate-key rejection;
- request-size, connection-count, and request-time bounds;
- no redirects, no CORS, and a restrictive Content Security Policy;
- redacted status with no path, secret, command, native diagnostic, or solver
  content.

The endpoint file contains only a startup ID, process ID, port, manifest hash,
and mode. It never contains the browser bearer secret.

## Current blockers

The authoritative status remains
[validation/manifests/m3-entry-gates.json](../../validation/manifests/m3-entry-gates.json).
At this revision:

- `productEnabled` is false;
- all runtime grants are empty;
- no code-owned product release profile exists;
- native three-platform runtime evidence is not approved;
- physical abrupt-power evidence is incomplete;
- solver license, immutable image, SBOM, and numerical-corpus approvals are
  incomplete.

The implementation can therefore be reviewed and exercised without making an
unsupported solver, security, platform, or numerical claim.

## Verification

```bash
npm run check:m3
npm run check
npm run local:doctor
npm run local:preview
```

`local:preview` is a long-running command. Stop it with Ctrl+C. The blocked
`local:serve` result is also a required fail-closed test for the committed
release.
