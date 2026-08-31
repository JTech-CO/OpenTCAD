# OpenTCAD architecture

[한국어](../ko/architecture.md)

## Product modes

OpenTCAD deliberately separates a safe static experience, a blocked local
preview, and an evidence-activated solver product.

| Mode | Where it runs | Can execute a deck? | Purpose |
|---|---|---:|---|
| Static preview | GitHub Pages or any static host | No | Explore the workflow, UI, terminology, and deterministic reference visuals |
| Local blocked preview | Loopback-only same-origin web server | No | Exercise the product connection UI without state, credentials, or a runtime |
| Activated local product | Loopback-only local web server plus OCI runtime | Only after release activation | Single-user process and device simulation |
| Shared/server | Managed host with authentication and quotas | Yes, after sandbox validation | Classroom, lab, or maintained server use |

The static build contains no runtime credentials, engine socket, subprocess
bridge, uploaded code execution, or hidden solver endpoint. Editing the deck
in static mode changes browser memory only. The blocked local preview serves
the same assets and a redacted status endpoint, but creates no durable state
and contacts no native service.

## Target local flow

```text
Browser
  │ same-origin HTTP
  ▼
Local API and static host
  ├─ strict bearer HTTP codecs
  ├─ bounded execution and control lanes
  └─ redacted product status
             │ typed requests
             ▼
      Local product service
  ├─ recovery-first startup
  ├─ maintenance and backup coordinator
  ├─ native credential store
  └─ durable SQLite state and fencing
             │ SandboxSpec only
             ▼
        Sandbox broker
             │ validated OCI operations
             ▼
 Docker or rootless Podman adapter
             │
   per-job managed volume
      ├─ approved process engine
      ├─ approved remeshing engine
      └─ approved device engine
```

The API does not execute simulators. The worker does not construct raw runtime
commands. Only the sandbox broker can reach the runtime, and it accepts a
typed, allowlisted request rather than arbitrary image, command, environment,
or mount values. The local service uses standard-library HTTP and SQLite; it
does not require FastAPI, PostgreSQL, or Redis.

## Product activation boundary

The product command checks the evidence-bound M3 manifest before reading
assets, creating local directories, opening credentials or databases, probing
an OCI runtime, or binding a socket. A second, code-owned release profile must
match the manifest digest, backend, images, and entrypoints exactly. The
committed release-profile set is empty, so changing operator configuration or
the manifest alone cannot activate execution.

After activation, one per-user instance runs at a time. It completes durable
recovery before API admission, starts the scheduled-backup coordinator, and
publishes only a secret-free endpoint record. Static assets and API responses
share one numeric loopback origin. The browser receives an ephemeral secret in
a URL fragment, removes the fragment immediately, and stores the secret in
memory only.

## Non-negotiable sandbox policy

Every real solver job must fail closed unless the runtime can enforce all of the following:

- no network;
- all Linux capabilities dropped;
- no-new-privileges;
- read-only root filesystem;
- fixed non-root UID/GID;
- exactly one isolated writable job volume;
- CPU, memory, PID, time, file-count, and output limits;
- no host namespace, device, runtime socket, or arbitrary bind mount;
- digest-pinned image and fixed entrypoint allowlists.

A SUPREM input deck is treated as arbitrary shell-capable input, not as a harmless domain-specific language. The browser never passes user content into an argv, image name, host path, environment key, or entrypoint.

## Static reference-data contract

The current UI uses deterministic, code-owned reference-preview values so the complete product shape can be reviewed before solver distribution is approved. Reference visuals are always labelled **not solver output**. They are not numerical baselines, cannot be exported as validated results, and must never be presented as converged data.

When a local engine is connected later, every result will carry provenance: app revision, runtime backend and architecture, image digests, engine versions, input hashes, convergence warnings, fallback decisions, and skipped points.

## Repository direction

```text
frontend/                 Static-compatible React application and local connection UI
docs/en/ and docs/ko/     Paired product and engineering documentation
.github/workflows/        CI and GitHub Pages deployment

backend/app/product/      Evidence gates and code-owned release profiles
backend/app/runtime/      Docker, Podman, policy, stable errors, native fencing
backend/app/broker/       Durable lifecycle, cancellation, recovery, archive, backup
backend/app/service/      Loopback host, worker, credentials, scheduler, CLI
config/                   Strict operator configuration example
validation/               External observations, comparators, schemas, and contract records
```

The runtime and service implementation is present and contract-tested, but the
committed product remains disabled. Docker or Podman is contacted only by an
activated product host. No third-party solver binary, approved solver image,
or numerical release corpus is distributed in this repository.
