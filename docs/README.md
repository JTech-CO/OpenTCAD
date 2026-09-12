# OpenTCAD documentation

[한국어](README.ko.md) · [OpenTCAD](../README.md)

## Start here

- [TCAD and supported simulations](en/simulation-guide.md): concepts, inputs, results, example experiments and limitations.
- [Windows local setup](en/windows-mvp.md): persistent jobs, cancellation, recovery and offline backup.
- [Laboratory setup](en/mvp-laboratory.md): calculator and experimental solver installation on Windows, macOS and Linux.

## Use the tools

- [2D MOSFET and SUPREM coupling](en/mos-process.md): physical models, numerical bounds and process CLI.
- [Original process mesh](en/process-mesh.md): supported structure files and explicit electrode mapping.
- [Reference workspace](en/m4-workspace.md): project files, imported data and illustrative views, separate from actual solves.
- [Local MCP](en/mcp.md): trusted AI-client integration and explicit execution permissions.

## Scope and contribution

- [Product and release scope](en/product-scope.md)
- [Licensing](en/licensing.md)
- [Architecture](en/architecture.md)
- [Development](en/development.md)
- [Validation](../validation/README.md) and [PN repeatability investigation](en/pn-repeatability.md)

## Maintainer reference, not a getting-started path

The M0-M2 documents and [code maps](CODEMAPS/README.md) remain at their existing paths because contract checks and, for M2, recorded content hashes depend on them. They are historical engineering evidence, not a current feature list or a prerequisite for using the laboratory.

The M3 [local-service](en/m3-local-service.md), [entry-gate](en/m3-entry-gates.md), [runtime-conformance](en/m3-native-adapter-conformance.md), [credentials](en/m3-native-credentials.md), [promotion](en/m3-promotion-readiness.md) and [solver-release](en/m3-solver-release-qualification.md) guides describe a separate, disabled OCI product track. They do not block the ordinary Windows MVP release scope or enable those features in it.

Active validation harnesses are retained to check numerical behavior, security and recovery. Obsolete implementation/site-comparison reports have been removed; their history is available in Git.
