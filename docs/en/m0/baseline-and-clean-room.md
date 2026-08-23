# M0 baseline freeze and clean-room policy

[한국어](../../ko/m0/baseline-and-clean-room.md) | [M0 status](README.md)

## Frozen references

| Reference | Commit | Permitted use |
|---|---|---|
| `ypooh2042/tcad-webapp` | `13bce4a9daba5796ceee633fb8cd0c870465f766` | Read-only behavior, architecture, dependency, and license evidence |
| OpenTCAD foundation | `4a7cae9b5192e52730f204b1236ff63a1abe3988` | First merged bilingual static foundation |
| OpenTCAD M0 parent | `f0305c8d4f79b8c8aea7683d52fd17bb61342001` | Parent of M0 discovery changes |

The machine-readable record is [`m0/BASELINE_FREEZE.json`](../../../m0/BASELINE_FREEZE.json). Moving branches or mutable image tags do not change this baseline.

## What is verified

The OpenTCAD static foundation builds, passes nine deterministic UI tests, has no known npm audit finding, and deploys to GitHub Pages. Its process profile and I-V curve are labeled reference preview data. This evidence verifies the UI foundation only.

No SUPREM or DEVSIM numerical result has been verified in OpenTCAD. The Linux reference run, three golden cases, repeated-run variance, immutable solver image digests, and fault-path observations remain pending.

## Required execution evidence

Each baseline run must record:

- repository commit, host OS and architecture, runtime version, and immutable image digests;
- input bytes and SHA-256;
- command contract, environment allowlist, resource limits, and exit classification;
- output, log, image, and metric hashes;
- node, element, region, contact, and artifact-size counts where applicable;
- process metrics, device curve metrics, and convergence semantics;
- repeated-run distribution, cancellation, timeout, output-limit, and restart behavior.

A zero exit code is not numerical success. A screenshot is not a golden result. Raw artifacts and machine-readable metrics are the source of truth.

## Clean-room boundary

OpenTCAD must reproduce observable behavior and documented interoperability contracts without copying the reference application's code, prose, assets, or internal organization.

Allowed inputs include:

- public product behavior observed through the UI or documented API;
- independently written requirements, test cases, schemas, and numerical invariants;
- public solver formats and interfaces needed for compatibility;
- license, provenance, dependency, and security facts required for review.

Disallowed inputs include:

- copying or translating reference application source, comments, documentation, or UI text;
- mechanically preserving internal names, file layout, control flow, or data structures when compatibility does not require them;
- importing reference screenshots or assets without explicit rights;
- placing third-party solver code or patches inside the MIT ownership boundary.

For solver-backed work, the preferred flow separates an observer/specification role from an implementer role. The observer records only externally testable behavior and required interfaces. The implementer works from that specification and OpenTCAD tests. Any contributor who has inspected reference internals must disclose that access in the review record.

This policy governs work from M0 forward. It does not by itself certify any work as a legally formal clean-room implementation.

## M0 source-access record

On 2026-08-23, M0 inventory review read the frozen reference's SUPREM license and provenance, backend dependency declaration, Compose service definitions, and three Containerfiles. The purpose was licensing, dependency, image, sandbox, and architecture characterization. No reference application source was copied into OpenTCAD.
