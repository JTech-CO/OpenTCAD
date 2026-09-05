# M3 promotion readiness

[한국어](../ko/m3-promotion-readiness.md)

The existing `check:m3` command validates the committed blocked state. It does not grant product authority and remains unchanged.

The separate promotion checker is for a future reviewed release candidate. No promotion-readiness manifest is committed while M3 remains blocked:

```sh
npm run check:m3:promotion -- \
  --manifest validation/manifests/m3-entry-gates.json \
  --readiness validation/manifests/m3-promotion-readiness.json \
  --revision <40-character-commit>
```

It requires a clean checkout of the exact revision, all eight gates approved together, Docker and Podman qualification evidence on Windows, macOS, and Linux, exact runtime grants, a version 2 release image lock, immutable image identities, SBOM hashes, license evidence hashes, and matching entrypoints. The six reviewed runtime records must match `validation/schemas/m3-native-qualification-evidence.schema.json`; review cannot predate observation. One missing or conflicting item blocks the whole candidate.

`M3 native qualification` is a manual self-hosted observation workflow. Configure its `m3-native-qualification` environment with required reviewers and restrict the `opentcad-m3`, platform, and backend labels to dedicated runners before use. Its inputs bind an exact 40-character revision and an exact fixture image reference, OCI index digest, platform-manifest digest, and image platform. The fixture must already exist in the selected runtime because the observer never builds, pulls, publishes, or removes it.

The workflow writes only to a new directory under the runner's external temporary directory. Windows Podman uses the fixed reviewed `Debian` WSL transport; other host and backend combinations use their native transport. It uploads either `manifest.json` or `failure.json`. A job succeeds only when every adapter scenario passes, cleanup leaves no managed objects, the selected runtime and image identity match, and every approval, qualification, distribution, and promotion field remains `false`.

A successful workflow artifact is still a non-promoting observation, not one of the six reviewed runtime qualification records accepted by the promotion checker. Creating such a record requires a separate human review and revision-bound evidence process. The workflow never edits the entry-gate manifest, release profiles, image lock, readiness record, or repository.

Run the non-promoting fixture suite with:

```sh
npm run test:m3:promotion
```

Fixture approvals and hashes exist only in temporary test directories. They are not release evidence.
