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

Run `npm run test:validation`, `npm run test:runtime`, or the complete `npm run check`. Use `npm run observe:base001 -- --help` to inspect the external-only observation interface. There is intentionally no baseline-update command, and the observer cannot write evidence inside OpenTCAD.
