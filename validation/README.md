# OpenTCAD validation foundation

[한국어](README.ko.md) | [M1 status](../docs/en/m1/README.md) | [Validation contract](../docs/en/m1/validation-contract.md)

This directory contains engine-independent M0 and M1 validation contracts plus the gated M2 runtime-foundation record. It contains no solver, authorized fixture, numerical baseline, or golden result.

- `baseline/`: external observation hashing, profile, log-policy, timeout, and repeatability code with unit tests
- `comparators/`: exact, topology, scalar, curve, repeatability, and report code with unit tests
- `faults/`: engine-independent timeout, cancellation, combined-output cap, and worker-reset supervisor with real child-process tests
- `corpus/`: candidate coverage manifest with null baseline values
- `manifests/`: gated M0/M1/M2 status, frozen contract evidence, and quarantined image references
- `plans/`: non-promoting external reference observation plans with no expected values
- `schemas/`: JSON schemas for corpus, report, observation plan, and observation envelopes

Run `npm run test:validation`, `npm run test:runtime`, `npm run check:m1`, and `npm run check:m2`. Use `npm run observe:base001 -- --help` to inspect the external-only observation interface. There is intentionally no baseline-update command, and the observer cannot write evidence inside OpenTCAD.
