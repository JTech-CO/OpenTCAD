# Solver release contract fixtures

> TEST FIXTURES ONLY. Nothing in this directory is product release evidence.

These files are synthetic data for exercising the M3 solver release validator. They do not contain real solver binaries, source archives, redistribution permissions, legal conclusions, production image attestations, approved SBOM reviews, or accepted numerical baselines.

The production CLI always rejects `evidenceClass: "contract-fixture"`. It also rejects every artifact path below `validation/solver-release/fixtures/` when a document claims to be `release-evidence`. Moving, copying, or relabeling these values does not turn them into qualification evidence.

Run the fixture suite with:

```console
node --test validation/solver-release/validator.test.mjs
```

Production candidates must be assembled from independently obtained and reviewed artifacts described in `docs/en/m3-solver-release-qualification.md`.
