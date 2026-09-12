# OpenTCAD architecture

[한국어](../ko/architecture.md) · [Documentation](../README.md) · [Simulation guide](simulation-guide.md)

## Current execution paths

| Path | Implementation | Execution boundary |
|---|---|---|
| Browser calculator | React and a code-owned analytical NMOS model | Runs in the browser, including GitHub Pages |
| Reference workspace | Illustrative project and result-inspection UI | No solver submission; mock lifecycle only |
| Experimental laboratory | Authenticated loopback HTTP and fixed native DEVSIM templates | Explicit PN/2D MOS submissions, one active solve |
| Windows local MVP | Laboratory plus exclusive SQLite history, recovery and offline backup | Windows process containment; fixed templates only |
| SUPREM process CLI | Explicit native or local container invocation, structure/contact transfer | Separate trusted-user opt-in; not a browser deck endpoint |
| M3 OCI product | Broker, runtime adapters and evidence-bound release profiles | Implemented separately, activation disabled |

These paths share the web interface but do not share every guarantee. The current laboratory is not the M3 sandbox broker. A shared multi-user solver service is not implemented.

## Laboratory data flow

The browser sends bounded numerical inputs to the same-origin loopback API. The service starts a fixed solver worker, reports job state and returns validated result records. It does not accept uploaded Python, shell commands or arbitrary process decks. Failure does not substitute analytical or reference data for solver output.

The service issues a private per-launch URL fragment. The browser consumes and removes it and keeps the token in memory only. Reopening the original private URL restores access after refresh. Tokens must not be shared or persisted in project/result files.

The Windows MVP adds exclusive state-directory ownership, SQLite job history, service/launcher termination cleanup and interruption classification on restart. Backup is offline and checksum-verified, not authenticated or encrypted. These controls do not protect against a malicious process with the same user's file access or establish physical power-loss durability. See [Windows operation](windows-mvp.md).

## Process transfer and automation

SUPREM runs through an explicit CLI using a separately installed trusted solver. The device service reads selected process/contact files at startup, verifies their supported structure and serves a fixed snapshot. Doping-only and original-mesh transfer are different modes; see [process coupling](mos-process.md) and [mesh transfer](process-mesh.md).

The [stdio MCP bridge](mcp.md) connects to the same authenticated numeric-loopback service. It is read-only by default. Explicit execution permission exposes fixed PN/MOS submission and cancellation, not arbitrary scripts, paths or an automatic sweep queue.

## Separate M3 track

The evidence-gated OCI product has durable ownership/fencing, a broker, Docker/Podman adapters, credential integration and maintenance/backup contracts. Its committed release profiles remain empty. The product command refuses activation before side effects; changing a manifest alone cannot enable it.

These contracts and their stricter runtime qualification are preserved as a separate track, not presented as guarantees of the current local MVP. See [M3 service](m3-local-service.md). Do not remove its validation checks or grant runtime authority while changing user documentation.

## Code ownership

- `frontend/src/mvp/`: calculator, laboratory and result-history UI.
- `backend/app/experimental/`: fixed PN/MOS workers, process transfer, Windows MVP and MCP.
- `backend/app/product/`, `runtime/`, `broker/`, `service/`: separate gated OCI service and contracts.
- `validation/`: numerical observations, evidence and contract checks.
- `docs/en/`, `docs/ko/`: paired user and maintainer guides.

Static assets contain no native solver. Reference data, analytical estimates, imports and real solver results must retain distinct provenance labels. For supported functionality rather than component internals, start with the [simulation guide](simulation-guide.md).
