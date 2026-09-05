# M3 solver release qualification

M3 solver release qualification is a fail-closed evidence check. Passing the contract fixture suite proves the validator behavior only. It does not approve a solver, image, license position, or numerical baseline.

## Production command

```console
node tools/check-m3-solver-release.mjs --candidate <reviewed-evidence.json> --root .
```

There is no production CLI switch that permits contract fixtures. The command accepts only an approved `release-evidence` document. The candidate must satisfy `validation/solver-release/schema.json`, and the validator independently checks exact object shapes, duplicate JSON keys, file containment, regular-file status, byte counts, and SHA-256 hashes.

## Required evidence

1. Source identity
   - Every source commit is exactly 40 or 64 lowercase hexadecimal characters.
   - Source archives, license texts, notices, corresponding source, patch provenance, patch ownership, and redistribution decisions are byte and hash bound.
2. Complete rights decisions
   - SUPREM-IV.GS source and patch redistribution are both approved.
   - DEVSIM, Gmsh, and transitive runtime obligations have accountable reviews.
   - No unresolved transitive license remains.
3. Immutable multi-platform images
   - The exact role set is `transfer`, `suprem`, `devsim`, and `gmsh`.
   - Every role has exactly one `linux/amd64` and one `linux/arm64` manifest.
   - Image and scanner references contain a digest and no mutable tag.
   - Each CycloneDX SBOM subject and its embedded `opentcad:subject-manifest-digest` property bind the platform manifest digest.
4. Numerical corpus
   - SUPREM-IV.GS, DEVSIM, and Gmsh each have one reviewed case.
   - Input, expected result, provenance, and observed result artifacts are hash bound.
   - Declared comparator and metric sets match the result exactly.
   - Tolerances are finite and non-negative, at least five repeats are required, and unlisted warnings fail.
   - Provenance binds the exact input, expected result, engine role, image index, platform, and platform manifest.
5. Review
   - Rights, reproducibility, SBOM, case, corpus, and final release reviews must all be approved by accountable reviewers.
   - Partial or blocked evidence cannot be promoted.

## Fixture boundary

`validation/solver-release/fixtures/valid-contract.json` is deliberately marked `contract-fixture` and uses reserved fixture identities. Its artifacts are synthetic. The product validator rejects that evidence class and rejects fixture-tree artifact paths even if a document is relabeled as production evidence.

Use the focused regression suite only to verify the contract:

```console
node --test validation/solver-release/validator.test.mjs
```

Legal permission, solver redistribution rights, platform image publication, SBOM review, numerical tolerance approval, and final release approval remain external human decisions. The validator records and verifies those decisions but cannot manufacture them.
