# PN repeatability investigation

[한국어](../ko/pn-repeatability.md) · [Windows MVP](windows-mvp.md)

The September 8 PN byte-identity failure remains unresolved. Its original two
result files were not retained, so the digest pair alone cannot establish whether
the difference was numerical, metadata-related, or an encoding difference.
Subsequent matching runs do not retroactively clear that failure.

## Capture a new observation

Use the already installed pinned DEVSIM environment and a new absolute output
directory. No solver download, arbitrary script or approval flag is involved.

```powershell
.\.venv-mvp\Scripts\python.exe -m backend.app.experimental.repeatability --output C:\absolute\new-pn-observation --cycles 12
```

On other hosts use `.venv-mvp/bin/python` with an absolute output directory.
This is a diagnostic tool, not additional platform qualification.

Each cycle runs 100, 200, 400, then 200 intervals in fresh solver processes, matching
the original failing test's order. Up to 50 cycles are allowed. The tool preserves
every original result and compares each with the first result having the same
input. It verifies saved result integrity using the existing replay reader and
records source-file hashes before and after the run.

`report.json` distinguishes byte identity from the existing numerical replay
tolerances. It includes changed fields, sample coordinates, maximum absolute and
relative differences, source drift, and exact file/result hashes. Signed zero
and integer/float encoding differences remain visible. It never rounds values,
changes tolerances, rewrites previous outputs, or clears a historical issue.
`failure.json` preserves an incomplete run's completed-file list if a solve fails.
Keep the entire output directory; the report alone is not the raw numerical evidence.

Exit 0 means only that this observation was stable. Exit 1 means observed
differences, invalid arguments or an incomplete observation. Release approval and
historical-issue clearance remain false even when every comparison matches.

## Automatic failure capture

The existing native PN regression still asserts exact result-hash and I-V equality.
Before a mismatching hash fails that assertion, it saves `before.json`, `after.json`
and `comparison.json` to a unique directory. Set `OPENTCAD_NUMERICAL_EVIDENCE_DIR`
to choose the parent; otherwise the OS temporary directory is used. A storage
failure does not bypass the original assertion.

Native CI uploads this directory on failure as a revision- and platform-labelled
artifact retained for 30 days. Download and preserve it before expiry. Synthetic
observer unit tests only verify diagnostic behavior; they are not solver evidence.

The [September 12 observation](../../validation/experimental/pn-repeatability-20260912.json)
records two 48-solve batches without a reproduced mismatch. Current 200-interval
results match the second historical digest. This narrows the investigation but
does not establish what produced the first digest. The Windows release remains
a candidate with the original issue open and dedicated-host review pending.
