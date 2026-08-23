# M1 validation contract

[한국어](../../ko/m1/validation-contract.md) | [M1 status](README.md)

## Corpus lifecycle

A case moves through two states only:

1. `pending-m0`: the case describes intended coverage but has no fixture path, input hash, baseline identifier, expected value, or approved engine.
2. `frozen`: authorized input bytes, immutable engine identity, raw artifacts, metrics, repeated-run evidence, warning policy, and review approval are all recorded.

CI cannot perform this transition and cannot write golden artifacts. A failed test is never fixed by replacing expected values in the same change.

## Comparator semantics

| Comparator | Contract |
|---|---|
| `exact-hash` | SHA-256 and byte length must match exactly |
| `topology` | Node, element, region, and contact counts are exact; material, region, and contact names are compared as duplicate-free sets |
| `scalar` | Values must be finite and pass `abs(actual - expected) <= max(absTolerance, relTolerance * scale)` |
| `curve` | Point count, ordering, x coordinate, y coordinate, and solve status are checked independently; skipped points fail by default |
| `repeatability` | At least five finite samples are required; observed range must fit the reviewed absolute or relative range gate |

`scale` is the greater absolute magnitude of the expected and actual scalar. NaN and infinity raise an error rather than being converted or ignored.

## Tolerance governance

- A tolerance is zero unless a reviewed manifest supplies a non-negative value.
- Absolute and relative tolerances are recorded separately with units and rationale in the frozen baseline.
- A porting change cannot modify engine version, physical model, convergence policy, and tolerance in the same review.
- Natural variance is measured before a tolerance is selected.
- A non-converged, skipped, missing, or reordered curve point is not repaired by interpolation in the comparator.

## Topology and curve negative controls

Unit tests intentionally change one topology count, skip a curve point, shorten a curve, and exceed a curve tolerance. These are framework controls only. M1 still requires negative controls using real frozen TCAD fixtures before exit.

## Reports

`buildValidationReport` produces deterministic JSON when the caller supplies the timestamp, baseline identifier, case identifier, metadata, and comparator results. `renderValidationReportHtml` renders that same object without scripts or external assets. The JSON object remains the authoritative result; HTML is a review surface.

A solver-backed report must include immutable repository, input, engine, image, architecture, raw artifact, and metric identities. The current report schema defines the common envelope but does not invent those values.

## Image lock

The image lock mirrors the six M0 image references so drift is visible. All digests, architectures, SBOM hashes, and approvals remain empty. An image can leave quarantine only when the exact manifest digest, supported platforms, SBOM, license review, and reproducible build evidence are recorded together.
