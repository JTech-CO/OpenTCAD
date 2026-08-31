# OpenTCAD validation foundation

[한국어](README.ko.md)

This directory contains engine-independent validation contracts and runtime-foundation records. It contains no solver, authorized fixture, numerical baseline, or golden result.

- `baseline/`: external observation hashing, profile, log-policy, timeout, and repeatability code with unit tests
- `comparators/`: exact, topology, scalar, curve, repeatability, and report code with unit tests
- `faults/`: engine-independent timeout, cancellation, combined-output cap, and worker-reset supervisor with real child-process tests
- `corpus/`: candidate coverage manifest with null baseline values
- `manifests/`: frozen contract evidence and quarantined image references
- `plans/`: non-promoting external reference observation plans with no expected values
- `schemas/`: JSON schemas for corpus, report, observation plan, and observation envelopes
- `evidence/m3/`: hash-bound implementation, host, platform, power-loss, and solver-release status records
- `power-loss/`: external physical power-cut qualification procedure

Run npm run test:validation, npm run test:runtime, npm run check:m3, or the complete npm run check. Use python tools/qualify-runtime.py --output validation/evidence/m3/runtime-host-local.json on a qualification host. A runtime observation does not grant approval. There is intentionally no baseline-update command.
