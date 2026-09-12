# OpenTCAD product and release scope

[한국어](../ko/product-scope.md) · [Windows MVP](windows-mvp.md)

## Direction confirmed by the project owner on September 12, 2026

OpenTCAD aims to be an open semiconductor process/device simulation platform
operated through a bilingual web UI on ordinary computers, without specialized
test equipment or institutional qualification as a prerequisite. Research-oriented
models, reproducible results, automation and a dedicated MCP interface are the
direction of development, not claims of already achieved instrument equivalence
or calibrated fabrication sign-off accuracy.

Static GitHub Pages runs the immediate analytical calculator and reference UI.
Actual SUPREM/DEVSIM execution requires a local solver service today. Web-based
operation does not mean those native solvers already execute inside a static
browser page. Hosted multi-user services and browser-native solver ports would
need separate implementation and validation.

## Ordinary software release criteria

- Working parameter editing, plots and spatial results with explicit model limits.
- End-to-end supported local solver workflows with fixed dependencies and provenance.
- Numerical regressions, repeatability, replay and documented tolerances.
- Authenticated execution, cancellation, process/launcher termination recovery,
  persistent result integrity and tested backup/restore.
- Exact-revision Windows acceptance and developer review, with English/Korean guidance.

Physical power cuts, PDU/relay hardware, a professional laboratory and independent
institutional review are **not required for this release track**. Software crash
tests are still required; they do not certify power-cut durability. The existing
eight-gate M3 qualification scheme is retained as an optional extended-assurance
track, not an obligation to complete before releasing ordinary OpenTCAD software.
Its evidence, runtime grants and disabled activation remain unchanged. Reusing
its components in the ordinary track requires scoped integration tests, not an
unreviewed bypass of runtime security checks.

The [Windows manifest](../../validation/manifests/windows-mvp-release.json) is still
a candidate, not a released product. Closing an incident does not approve a release.

## Historical PN incident

The owner reports external log corruption by another Codex subagent during
concurrent work, also observed in other projects. The
[disposition](../../validation/experimental/pn-incident-disposition-20260912.json)
closes this historical release blocker on that stated basis. The missing original
result pair prevents independent forensic confirmation. Original observations
remain untouched. Exact-hash assertions, numerical tolerances and raw failure
capture remain in force; a new mismatch requires its own investigation.

## Upstream and solver licensing

The owner reports direct confirmation from the author of
[tcad-webapp](https://github.com/ypooh2042/tcad-webapp) that the upstream app is MIT
licensed. This is an owner-reported confirmation, not a publicly verified license
file or a license grant authored by OpenTCAD. Preserve the author's written
confirmation, applicable revision and attribution when available.

That report concerns the upstream web app, not every solver or dependency.
Component notices and terms still apply. The current release remains source-only
with user-installed solvers. Bundled images/installers require their own component
inventory, applicable notices and redistribution review. Numerical regression and
reproducibility remain software quality requirements, without requiring an
external institution to approve a corpus.

## Next development sequence (planned, not completed)

1. Finish ordinary Windows acceptance and release review.
2. Improve the integrated process/device workflow, history/reopening, parameter
   sweeps, comparison and export UI.
3. Add a dedicated local MCP interface over the validated job service: capability
   discovery, input schema, submit/status/cancel, result/provenance retrieval and
   bounded sweeps. Start with read-only access; require explicit authorization for
   computation and writes. Do not expose arbitrary shell, Python or file paths.
4. Expand supported materials, structures, physical models and numerical reference
   cases; qualify each claimed capability and platform with reproducible tests.

AI should orchestrate validated solver operations and explain their provenance,
not fabricate solver output or treat an AI answer as numerical verification.
