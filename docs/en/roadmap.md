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

The foundation milestone is being implemented. M0 solver distribution remains gated because the SUPREM notice is not MIT. The upstream application is used as read-only behavior and architecture evidence; it is not copied into this MIT repository.

## Static and local delivery

GitHub Pages remains available throughout the roadmap as a safe product preview and documentation surface. It will never become a shortcut around the sandbox. Solver-backed operation belongs to the loopback-only local stack or an authenticated managed server.

No milestone may mark a result “successful” solely because a process exits. Topology invariants, process metrics, I–V metrics, convergence semantics, provenance, and cross-platform tolerances are separate release gates.
