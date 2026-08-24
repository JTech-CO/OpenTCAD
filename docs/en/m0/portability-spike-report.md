# M0 portability spike report

[한국어](../../ko/m0/portability-spike-report.md) | [M0 status](README.md)

## Status

No host-support result is claimed yet. Windows Docker Desktop and WSL2 Debian rootless Podman now provide both solver-run diagnostics and a passing non-solver OCI fault characterization, and a separate controlled Podman build reproduces exactly. The two solver-run observations remain ineligible because of declared log failures, while the controlled image and fault image remain non-baseline and non-distributable pending rights, SBOM review, corpus evidence, and approval. Host comparisons must use reviewed image identities before support conclusions are possible.

## Test matrix

| Host and runtime | Question | Evidence required | Status |
|---|---|---|---|
| Linux x86-64, rootless Podman | Can the frozen reference reproduce the selected process and device cases? | Runtime version, image digests, full transcript, metrics, fault paths | WSL2 non-solver fault matrix passed; clean solver baseline pending |
| Windows 11 x64, Docker Desktop WSL2 | Which mount, UID, signal, networking, and resource-limit contracts differ? | Same inputs and images, diagnostic bundle, structured failures | Non-solver policy and fault matrix passed, support undecided |
| Windows 11 x64, Podman Machine | Does the runtime-neutral contract work without `--userns keep-id` assumptions? | Capability probe and adapter trace | Pending |
| macOS Apple Silicon, Docker Desktop | Can amd64 images run explicitly under emulation and remain numerically acceptable? | Architecture identity, emulation flag, metrics, runtime observations | Pending |
| macOS Apple Silicon, Podman Machine | Which VM mount and signal behaviors differ? | Capability probe, adapter trace, metrics | Pending |
| Linux arm64 compile-only SUPREM | Does the legacy pointer model compile safely before native execution is considered? | Compiler output and static diagnostics only | Pending and non-release |

## Observed Windows preflights

The [BASE-001 observation report](base001-reference-observation.md) records five hardened Docker runs and five WSL2 rootless Podman runs of the frozen 1D boron deck. Both runtimes produced the exact same structure hash and record counts, and Podman passed the declared profile checks. Those original no-cache rebuilds drifted and every solver run still emitted declared command-input errors despite exit code 0. A later controlled build pinned bases, package snapshots, and timestamps and produced the same image twice plus an external local-only SBOM. This improves the image evidence but does not promote either run or establish host support. The separate [OCI fault matrix](oci-fault-matrix.md) then applied the same pinned non-solver Debian image and reviewed policy to both runtimes. Six named scenarios and 20 mixed-loop cases passed on each runtime with exact-name removal and zero final labelled containers. Podman required `--read-only-tmpfs=false` to match Docker temporary-filesystem semantics.

## Pass conditions

- Every run identifies the host, runtime, engine architecture, image digest, and whether emulation is active.
- Unsupported sandbox capabilities fail closed with an actionable diagnostic.
- The same normalized input and golden comparator are used across hosts.
- Process topology and device curve gates pass independently of process exit status.
- Host paths never become an implicit engine contract.

Results will be added only with reproducible evidence. Until then, the 1.0 host support matrix remains undecided.
