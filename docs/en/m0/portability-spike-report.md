# M0 portability spike report

[한국어](../../ko/m0/portability-spike-report.md) | [M0 status](README.md)

## Status

No host-support result is claimed yet. A Windows Docker Desktop preflight now provides diagnostic evidence, but it is ineligible for the Linux rootless Podman baseline and the local image did not reproduce byte-for-byte. Running different, mutable images on each host would still produce misleading platform conclusions.

## Test matrix

| Host and runtime | Question | Evidence required | Status |
|---|---|---|---|
| Linux x86-64, rootless Podman | Can the frozen reference reproduce the selected process and device cases? | Runtime version, image digests, full transcript, metrics, fault paths | Pending baseline |
| Windows 11 x64, Docker Desktop WSL2 | Which mount, UID, signal, networking, and resource-limit contracts differ? | Same inputs and images, diagnostic bundle, structured failures | Preflight observed, support undecided |
| Windows 11 x64, Podman Machine | Does the runtime-neutral contract work without `--userns keep-id` assumptions? | Capability probe and adapter trace | Pending |
| macOS Apple Silicon, Docker Desktop | Can amd64 images run explicitly under emulation and remain numerically acceptable? | Architecture identity, emulation flag, metrics, runtime observations | Pending |
| macOS Apple Silicon, Podman Machine | Which VM mount and signal behaviors differ? | Capability probe, adapter trace, metrics | Pending |
| Linux arm64 compile-only SUPREM | Does the legacy pointer model compile safely before native execution is considered? | Compiler output and static diagnostics only | Pending and non-release |

## Observed Windows preflight

The [BASE-001 observation report](base001-reference-observation.md) records five hardened Docker runs of the frozen 1D boron deck. The structure and record counts were exact across all runs and matched the frozen reference fixture blob. Every run also emitted declared command-input errors despite exit code 0, the required Podman/rootless profile was not met, and a no-cache image rebuild produced a different digest and layers. The result is diagnostic only and remains `ineligible`.

## Pass conditions

- Every run identifies the host, runtime, engine architecture, image digest, and whether emulation is active.
- Unsupported sandbox capabilities fail closed with an actionable diagnostic.
- The same normalized input and golden comparator are used across hosts.
- Process topology and device curve gates pass independently of process exit status.
- Host paths never become an implicit engine contract.

Results will be added only with reproducible evidence. Until then, the 1.0 host support matrix remains undecided.
