# Product and release scope

[한국어](../ko/product-scope.md) · [Simulation guide](simulation-guide.md) · [Windows setup](windows-mvp.md)

## Current scope

OpenTCAD targets semiconductor education and numerical experimentation on ordinary computers. The current source provides an immediate calculator, fixed local PN/2D MOSFET templates, experimental SUPREM transfer, result history and an initial local MCP bridge. English is the default and Korean is supported.

The Windows 11 x64 local MVP is a **source-only release candidate**, using separately installed solvers. The [release manifest](../../validation/manifests/windows-mvp-release.json) still records `candidate-not-released` and no owner release approval. A deployed Pages build is not a formal solver-product release.

The [dedicated Windows acceptance record](../../validation/experimental/windows-mcp-acceptance-20260912.json) covers implementation revision `8b84ce7`: native Windows/solver/MCP tests, frontend tests and browser workflows passed. That implementation is now merged into `main`, and Pages deployment completed at `e51a96f`. The record's pending merge/publication note describes its original review time; final owner release/version approval and a release tag remain outstanding. Historical evidence is not rewritten.

## Ordinary software release criteria

- Parameter editing, plots and spatial results with explicit model limits.
- Supported end-to-end local solves with pinned dependencies and provenance.
- Numerical regression, replay and declared tolerances.
- Authenticated execution, cancellation and software-interruption recovery.
- Integrity checks, offline backup/restore and bilingual operating instructions.
- Exact-implementation Windows acceptance and an explicit owner release decision.

As directed by the project owner on 2026-09-12, specialized power-control equipment, physical power-cut qualification and independent institutions are **not prerequisites** for this ordinary release. Numerical and software-recovery checks remain required.

The older M3 OCI qualification is a separate optional assurance track. Its manifests, evidence and disabled release profiles remain unchanged; its unapproved features are not silently activated in the MVP.

## Limits to disclose

GitHub Pages executes the calculator and reference UI, not native solvers. Real solves require the local service. SUPREM uses an explicit CLI and supported structure transfer, not an arbitrary browser process editor. MCP sweep planning does not automatically execute a queue.

The current release scope does not claim macOS/Linux product qualification, physical power-loss durability, same-user tamper resistance, OS-protected rollback prevention, authenticated/encrypted MVP backups or automatic scheduled MVP backups. The offline backup is checksum-based.

The physical models are limited and not calibrated to fabrication measurements. OpenTCAD is not a sign-off tool or a claim of equivalence to professional measurement equipment. See [supported experiments and exclusions](simulation-guide.md).

## Distribution and provenance

Original OpenTCAD code and documentation use MIT; this does not relicense external solvers. No solver source or binary is bundled. Solver-containing images/installers require their own component review and notices; see [licensing](licensing.md).

The owner reports direct confirmation that the original `tcad-webapp` author uses MIT. This is an owner-supplied report, not an independently verified public license file, and it does not cover every solver dependency. Preserve written confirmation and the covered revision when available.

The historical PN mismatch and later machine-metadata reproduction/fix are documented in [PN repeatability](pn-repeatability.md). Original observations remain preserved; exact hash and numerical checks have not been relaxed.
