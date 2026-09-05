# M3 native adapter conformance

This observation exercises the real `OciRuntimeBackend` against Docker or rootless Podman. It is intentionally separate from the M0 direct-CLI fault collector. The M0 record remains frozen and does not claim product-adapter or host qualification.

The observation is always non-promoting. A passed record still fixes `qualified`, `approvalGranted`, `baselinePromotionAllowed`, `releaseImageApproved`, `solverApprovalGranted`, and `platformApprovalGranted` to `false`. It does not modify the product entry-gate manifest or the code-owned release profiles.

## Fixture boundary

`validation/fixtures/m3-runtime` is an engine-free Debian fixture. It contains fixed entrypoints for canonical archive import and export, deterministic success, declared nonzero exit, sleep, and sustained output pressure. The output-pressure entrypoint remains alive after emitting more than the reviewed limit, so natural process exit cannot satisfy the streaming-termination case. The fixture contains no SUPREM-IV.GS, DEVSIM, solver license, network client, or operator-selected command path.

The observer does not build, publish, pull, or remove this image. A separate controlled setup must publish the reviewed source to exactly `localhost:5001/opentcad-m3-runtime-fixture`, resolve its OCI index and platform-manifest digests, and preload the same digest into the selected runtime. The observer then uses the adapter's pull-never path. Its image preflight must contain at least one local `image inspect`, no `image pull`, and exactly zero `manifest inspect` commands. A pre-existing fixture image is never deleted.

## Run

Use Python 3.12 or newer. The output directory must be an absolute, non-existing directory outside the repository.

Docker on the current host:

```text
python tools/observe-m3-native-adapter.py \
  --runtime docker \
  --image-reference localhost:5001/opentcad-m3-runtime-fixture@sha256:<index-hex> \
  --index-digest sha256:<index-hex> \
  --platform-manifest-digest sha256:<platform-manifest-hex> \
  --platform linux/amd64 \
  --output <absolute-external-directory>
```

Rootless Podman in the reviewed Windows WSL transport:

```text
python tools/observe-m3-native-adapter.py \
  --runtime podman \
  --wsl-distribution Debian \
  --image-reference localhost:5001/opentcad-m3-runtime-fixture@sha256:<index-hex> \
  --index-digest sha256:<index-hex> \
  --platform-manifest-digest sha256:<platform-manifest-hex> \
  --platform linux/amd64 \
  --output <absolute-external-directory>
```

On Linux or macOS, Podman is invoked directly and `--wsl-distribution` is forbidden. On Windows, only the exact shell-free prefix `wsl.exe -d Debian -- podman --cgroup-manager=cgroupfs` is accepted.

## Protected manual workflow

The `M3 native qualification` workflow dispatches the same observer on a protected self-hosted runner. Supply the exact candidate revision and all four immutable image identity values. The selected platform and backend are also runner labels, and the workflow verifies the actual host before observation. On Windows Podman, it adds the reviewed `--wsl-distribution Debian` argument automatically.

The output path is a new directory under `runner.temp`, outside the checkout. The artifact contains `manifest.json` on a completed observation or `failure.json` on a blocked or failed observation. The final workflow step requires `observedConformancePassed` to be `true`, exact runtime and image identity agreement, zero remaining managed containers and volumes, and every authority-bearing field to remain `false`. Therefore a green workflow run records adapter behavior but grants no qualification or product authority.

## Scenarios

The plan runs these cases in order:

1. canonical input, deterministic workload, canonical artifact export, and exact cleanup;
2. declared nonzero exit;
3. external cancellation;
4. timeout classification;
5. streaming output-limit termination while the fixture remains alive;
6. stale fencing rejection with no native call;
7. concurrent cleanup idempotence.

Every native object is discovered by the managed and job labels, inspected, checked against a fence pair recorded for this run, and removed by exact name. Global container, volume, or image prune is forbidden. The final result requires zero matching containers and zero matching volumes. The external `state/cleanup-journal.json` retains exact identities for recovery after an abrupt observer interruption.

## Evidence

`manifest.json` is written only when the complete observation finishes. `failure.json` is written for a blocked preflight or unexpected failure. Command stdout and stderr are not stored; the record contains bounded byte counts and SHA-256 hashes. A scenario failure remains a failure. In particular, timeout, output-pressure, fencing, or cleanup defects are never converted into a passing result. Overall conformance additionally requires `streamingOutputTerminationProven` and `offlineLocalImageInspectionProven` to be `true`, `manifestInspectCommands` to be zero, and every scenario cleanup to have no adapter error.

Raw evidence stays outside the repository and is not a release-image, solver, baseline, platform, or product-approval input. A separate reviewed promotion process would be required even after all observation cases pass.
