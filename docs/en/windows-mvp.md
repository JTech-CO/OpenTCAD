# Windows-first local MVP candidate

[한국어](../ko/windows-mvp.md) · [Solver installation](mvp-laboratory.md)

This is a separate, source-only release track for Windows 11 x64. Under the
[owner-confirmed scope](product-scope.md), specialized hardware and institutional
qualification are not prerequisites. The original M3 gates remain an optional
extended-assurance track, not a blocker for this ordinary software release. The committed
[criteria](../../validation/manifests/windows-mvp-release.json) remain a candidate.
[Technical acceptance](../../validation/experimental/windows-mcp-acceptance-20260912.json)
is complete; the owner's final release decision is pending. This is not independent
M3 qualification. See the [current release scope](product-scope.md).

## Install and run

Install Node.js 22/24 and 64-bit Python 3.12-3.14. From the repository:

```powershell
npm ci
py -3.12 -m venv .venv-mvp
.\.venv-mvp\Scripts\python.exe -m pip install -r backend/app/experimental/requirements.txt
npm run build
npm run local:mvp -- doctor
npm run test:mvp:solver
npm run local:mvp -- serve
```

Dependency installation downloads third-party packages chosen by the user; the
repository and this track do not distribute solvers or approve their licenses.
Doctor checks pinned dependencies, Python, the host and built frontend without
starting a solver or claiming numerical acceptance. Serve also requires a real
startup PN solve. An unavailable Windows process-containment mechanism blocks
startup. No Docker or Podman service is required for native DEVSIM.

Open the private URL printed by the service. Keep the fragment access token
private. Only authenticated loopback requests run fixed numerical templates.
The immediate calculator still works on static Pages; native solves do not.
The browser continues to identify the service as experimental. No M3 product
activation token or runtime grant is issued by this command.

Use `--suprem-structure C:\absolute\process.str --suprem-contacts C:\absolute\contacts.json`
with serve to use the [original process mesh](process-mesh.md). SUPREM processing
remains a separate opt-in fixed-deck CLI using the user's own trusted installation.
It is not an arbitrary deck upload endpoint or a distributed solver image.

## State, interruption and result retrieval

The default state directory is `%LOCALAPPDATA%\OpenTCAD\windows-mvp`.
Use `--state-directory C:\absolute\project-state` for another local directory.
Linked/reparse paths are rejected; keep state on trusted local storage under your
own Windows account, not a shared or network folder. Only one server or offline
operation may hold the directory lock. This is not an adversarial same-user
filesystem security boundary.

Each directory holds at most 32 jobs, with records bounded to 1 MiB each. Nothing
is silently evicted. At capacity, stop the service, back up/export the results,
and use a new directory. Reusing an ID with different inputs remains a conflict.
Use **History / compare** and **Refresh history** to reopen stored PN/2D results,
inspect provenance, compare compatible final-current values and export a result.
This is read-only and does not replace editor inputs or execute a new solve.
Browser refresh removes the in-memory access token; reopen the private service
URL to authenticate again. No token is stored in browser persistent storage.
After stopping the service, retrieve records using:

```powershell
npm run local:mvp -- history
npm run local:mvp -- export --job-id ACTUAL_JOB_UUID --file C:\absolute\new-result.json
```

The exported result has the existing numerical result format. Import it through
the laboratory's existing file flow or replay it with the matching source and
solver version. The API also supports authenticated `GET /v1/lab/jobs` summaries
and `GET /v1/lab/jobs/{id}` details. No file path is accepted over HTTP.

A Windows kill-on-close Job Object contains the service and its descendants.
Each solver also has a separate job, attached to its announced worker PID before
input is delivered. This avoids mistaking the venv launcher for the real solver.
The lifecycle uses [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
The service also watches the launcher handle, covering abrupt npm or venv-launcher
termination. Normal cancellation kills/reaps the solver before acknowledgement.
SQLite transactions record admission and terminal results. On restart, a recorded
running job becomes failed with `error: interrupted`; it never becomes success or
automatically reruns. Storage failure blocks new admission and suppresses an
unpersisted success response. This does not promise physical power-cut durability.

## Offline backup and restore

Stop the service first. Outputs must be new files; restore requires a new directory.

```powershell
npm run local:mvp -- backup --file C:\absolute\new-backup.json
npm run local:mvp -- verify-backup --file C:\absolute\new-backup.json
npm run local:mvp -- restore --file C:\absolute\new-backup.json --state-directory C:\absolute\new-restored-state
npm run local:mvp -- serve --state-directory C:\absolute\new-restored-state
```

Backups are bounded JSON with record/result hashes and an aggregate SHA-256.
Duplicate keys, duplicate job IDs, altered hashes and invalid state/result pairs
are rejected. Restore inserts validated records in one transaction, never imports
a raw SQLite database, overwrites a project, runs a solver or restores a token.
A partial output file is not a valid backup. Confirm verification before archiving.

These are **checksums, not authentication or encryption**. A person able to rewrite
the file can recompute them. Backups exclude authentication secrets, installed
solvers, source code, STR/contact files and OS credential stores. Preserve matching
source and process files separately for replay. Importing an older intact backup
is allowed: there is no MVP anti-rollback floor or automatic scheduled backup.

## Acceptance before a Windows release

On the dedicated Windows host, record the exact clean commit, OS/Python/dependency
versions, doctor output and `npm run check` / `npm run test:mvp:solver` logs. Exercise
the real authenticated PN and MOS flows, changed bias response, cancellation,
abrupt service/launcher termination, restart interruption, history export, backup
tamper rejection and restore into a new directory. Include process-file hashes if
SUPREM coupling is claimed. Review this evidence before approving or tagging a
Windows release; green CI alone does not fill in `releaseReview`.

From a clean checkout, `npm run accept:windows -- --output C:\absolute\new-evidence`
runs the full check, doctor and native solver suite sequentially. It captures
revision, host, logs and hashes and fails if the source changes. The output is an
automated observation, never a self-issued release approval. Use an ignored
evidence directory such as a new child of `.experimental-results`.
For AI clients, see the [local MCP guide](mcp.md).

The [local observation](../../validation/experimental/windows-mvp-observation.json)
records a passing 35-test native suite and an earlier PN repeat hash mismatch.
The owner subsequently reported external log corruption during concurrent Codex
subagent work. The [incident disposition](../../validation/experimental/pn-incident-disposition-20260912.json)
removes that historical release blocker on the owner's report, not on an
independently reproduced cause or a solver fix. Original observations and exact
assertions remain unchanged. Any new mismatch requires investigation.
The subsequent dedicated-host run reproduced the exact digest pair: only machine
metadata differed. The [captured finding and fix](pn-repeatability.md) now explains
this pair; a native Windows metadata query replaces the WMI fallback.
Use the [PN investigation guide](pn-repeatability.md) to retain full repeated
results and inspect field-level differences without relaxing the acceptance test.

Physical abrupt-power durability and independent institutional qualification are
not required or claimed for this release. macOS/Linux product qualification,
automatic backup, OS-protected anti-rollback, bundled solver redistribution review
and externally calibrated numerical accuracy remain unverified or deferred.
Numerical regression and replay remain required without external corpus approval.
Original M3 commands, profiles and evidence gates remain unchanged. The OG image
and public Pages deployment are not changed by this track.
