# OpenTCAD validation foundation

[한국어](README.ko.md) | [M1 status](../docs/en/m1/README.md) | [Validation contract](../docs/en/m1/validation-contract.md)

This directory contains engine-independent M1 validation contracts. It contains no solver, authorized fixture, numerical baseline, or golden result.

- `comparators/`: exact, topology, scalar, curve, repeatability, and report code with unit tests
- `corpus/`: candidate coverage manifest with null baseline values
- `manifests/`: gated M1 status and quarantined image references
- `schemas/`: JSON schemas for corpus and report envelopes

Run `npm run test:validation` and `npm run check:m1`. There is intentionally no baseline-update command.
