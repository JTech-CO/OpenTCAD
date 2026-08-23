# M1 reproducibility and validation status

[한국어](../../ko/m1/README.md)

M1 is `gated-active`. OpenTCAD is implementing engine-independent validation contracts, but the M1 entry gate is not met because M0 has no authorized immutable solver images, frozen example metrics, or approved source-development license scope.

No file in this M1 foundation is a numerical baseline or solver result.

## Workboard

| Work item | Status | Current result |
|---|---|---|
| BASE-002 process corpus | Candidate manifest | Five process cases are declared with no source or expected values |
| BASE-003 `.str` topology corpus | Candidate manifest | Required topology fields are declared; fixture is quarantined |
| BASE-004 DEVSIM I-V corpus | Candidate manifest | Four device cases are declared; curves and metrics remain empty |
| BASE-005 comparator and report | Foundation implemented | Exact hash, topology, scalar, curve, repeatability, JSON, and HTML contracts have unit tests |
| BASE-006 pull-request CI | Foundation extended | Repository, M0, M1, punctuation, lint, test, and build gates run in CI |
| BASE-001 external observation | Harness implemented, result ineligible | Rootless Podman matched five Docker structure outputs exactly, but log failures, image rebuild drift, rights, SBOM, and review gates block promotion |
| Reproducible image lock | Quarantined | Six mutable references remain quarantined; Docker and Podman identities drifted, and only the Docker image has an external unreviewed SBOM |
| M1 exit | Not met | Linux baselines, five-run variance, and numerical PR smoke remain pending |

## Artifacts

- [Validation contract](validation-contract.md)
- [BASE-001 external observation](../m0/base001-reference-observation.md)
- [Reference observation plan](../../../validation/plans/base001-process-1d-boron.json)
- [Reference observation tests](../../../validation/baseline/observation.test.mjs)
- [Candidate corpus](../../../validation/corpus/index.json)
- [M1 foundation manifest](../../../validation/manifests/m1-foundation.json)
- [Image lock quarantine](../../../validation/manifests/image-lock.json)
- [Corpus schema](../../../validation/schemas/corpus.schema.json)
- [Report schema](../../../validation/schemas/report.schema.json)
- [Comparator implementation](../../../validation/comparators/index.mjs)
- [Comparator tests](../../../validation/comparators/comparators.test.mjs)

`npm run check:m1` rejects invented expected values, unfrozen fixture paths, unknown comparators, image approvals without evidence, M0 hash drift, and automatic baseline-update commands. `npm run test:validation` verifies the comparator behavior, including intentional topology, curve, and repeatability failures.

## Next gates

1. Finish or explicitly resolve the applicable M0 license and Linux baseline gates.
2. Select independently authored or authorized fixture inputs and freeze their SHA-256 values.
3. Pin exact engine and image identities, generate SBOMs, and record architecture metadata.
4. Run every candidate on the same Linux baseline five times.
5. Review natural variance before setting any tolerance or expected value.
6. Add a numerical PR smoke only after the reviewed baseline is immutable.

The implementation deliberately provides no command that updates a baseline automatically.
