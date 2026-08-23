# OpenTCAD milestone roadmap

[한국어](../ko/roadmap.md)

The detailed planning source is `03_MILESTONE_ROADMAP_KR.md`. This bilingual summary states the public product sequence and does not replace milestone entry or exit gates.

| Milestone | Outcome | Hard gate |
|---|---|---|
| Foundation | MIT-owned bilingual static app, Pages, CI, architecture and license boundary | Static mode cannot execute input |
| M0 | Upstream/dependency inventory, distribution decision, Linux baseline, platform spikes | License and baseline Go/No-Go |
| M1 | Golden process/device corpus, numerical comparator, reproducible image lock, CI foundation | Repeatable topology and metric evidence |
| M2 | Runtime protocol, Docker/Podman adapters, sandbox broker, managed job volumes | Policy fail-closed on both runtimes |
| M3 | Portable local stack, loopback-only local mode, launcher, doctor, backup skeleton | One-command local alpha |
| M4 | Windows 11 qualification | Docker Desktop WSL2 end-to-end and numerical evidence |
| M5 | macOS and multi-architecture qualification | Apple Silicon native or explicit amd64-emulation policy |
| M6 | Correctness, numerical stability, data safety, and UX defect burn-down | No open P0/P1 or known silent-correctness defect |
| M7 | Portable `.tcadproj`, provenance, diagnostics, engine registry | Cross-OS replay and secure import |
| M8 | Security, licensing, release operations, documentation, full qualification | 1.0 GA gates and rollback evidence |

## Current status

The foundation milestone is complete and deployed on GitHub Pages. M0 remains active, with frozen provenance, licensing, architecture, and baseline records in the [M0 workboard](m0/README.md). Windows Docker Desktop and WSL2 rootless Podman each produced five exact structure outputs; the Podman run met the declared environment profile, but clean-log, reproducible-image, SBOM, rights, and numerical-review gates still fail. M1 is `gated-active`: the [validation foundation](m1/README.md) implements candidate manifests and tested comparators but contains no fixtures or numerical baseline. Solver distribution remains blocked because the SUPREM notice and reference patches are not cleared for the intended bundle. The upstream application remains read-only evidence and is not copied into this MIT repository.

## Static and local delivery

GitHub Pages remains available throughout the roadmap as a safe product preview and documentation surface. It will never become a shortcut around the sandbox. Solver-backed operation belongs to the loopback-only local stack or an authenticated managed server.

No milestone may mark a result “successful” solely because a process exits. Topology invariants, process metrics, I–V metrics, convergence semantics, provenance, and cross-platform tolerances are separate release gates.
