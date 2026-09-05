# M4 workspace: projects, inspection, and comparison

[한국어](../ko/m4-workspace.md)

M4 implements the workspace features that do not require M3 product activation.
The same frontend is used by the static build and local preview. M3 remains
unapproved; project files, imported results, and mock actions cannot grant runtime
authority. This branch's implementation is not a claim that the public `main`
deployment has already been updated.

## Project workflow

1. Open the workspace and enter a project name.
2. Edit the illustrative deck in **Process**. Diagnostics identify a line and move
   editor focus to it. Unknown syntax is a warning; this is not a complete SUPREM
   parser, an engine readiness check, or a numerical validity check.
3. Edit gate/drain bias and temperature in **Device**. Preview limits are -10 to
   10 V and 1 to 1500 K, not solver-qualified operating ranges.
4. Use **Save project file** to download `opentcad-project.json`.
5. **Open project file** stages an import for review. The current project is only
   replaced after **Replace current project**. Discarding or a failed import
   preserves current editing state.

Project JSON has exactly `format: "opentcad-project"`, `schemaVersion: 1`, `name`,
`deck`, and `bias`. The bias object has exactly `gateVoltage`, `drainVoltage`, and
`temperature`. Names are 1 to 80 characters; decks allow up to 65,536 characters.
The deck checker accepts at most 2,000 lines and displays at most 100 diagnostics,
prioritizing errors so warnings cannot hide a blocker. Drafts with invalid deck
syntax may still be saved, but cannot start the mock workflow while errors remain.

Files are the persistence mechanism. The workspace does not automatically save
projects, imported results, or job state to browser storage or a server. Save
before reloading, and retain original result files. Downloads contain project
inputs only, never API tokens, approval records, or a resumable real job.

## Device inspection

The reference NMOS drawing supports region/terminal selection, 100% to 400% zoom,
bounded pan buttons, pointer dragging, and keyboard arrows. `+`/`-` zoom and
`Home` fits the drawing while the drawing region is focused. Keyboard-selectable
controls provide the same region selection without requiring a pointer.

The reference geometry and reference curves remain explanatory fixtures. Editing
a deck or bias does not regenerate them. Region shape, layer thickness, and
device response must not be interpreted as simulated results.

## Imported results

In **Compare**, open **File formats and examples** to download illustrative JSON
examples for I-V, profiles, and material maps. These examples are not solver
results or qualification evidence. JSON and CSV files must be valid UTF-8 and no
larger than 1 MiB. At most eight files are retained in the current workspace.
Duplicate JSON keys, unknown fields, non-finite numbers, oversized collections,
and unsupported units are rejected before display.

CSV is deliberately a two-column numeric format without quoted fields or metadata:

```csv
vd_v,id_ma_per_um
0,0
0.5,0.1
1,0.2
```

For profiles, use `depth_um,concentration_cm-3` as the exact header. Each curve
contains 2 to 2,000 points with strictly increasing x. Profiles require positive
concentration and non-negative depth. Curve x values are bounded to ±1e6 (depth
starts at 0); y values are bounded to ±1e30 (profile minimum 1e-30).

Curve JSON uses exactly:

```json
{
  "format": "opentcad-result",
  "schemaVersion": 1,
  "kind": "iv",
  "name": "External run",
  "source": "Unreviewed source description",
  "xUnit": "V",
  "yUnit": "mA/um",
  "points": [[0, 0], [1, 0.2]]
}
```

For profiles use `kind: "profile"`, `xUnit: "um"`, `yUnit: "cm^-3"`.
The chart uses logarithmic y for profiles and linear y for I-V. Sample tables
retain the original numeric values, even when graph labels are rounded.

Structure JSON replaces `xUnit`, `yUnit`, and `points` with `unit: "um"`, positive
`width` and `height`, and `regions`. It uses `kind: "structure"`. Each of 1 to 64
regions has exactly `id`, `material`, `x`, `y`, `width`, and `height`; IDs are
unique and rectangles must stay within the declared extent. Coordinates begin
at the upper-left and y increases downward. File order determines stacking of
overlapping rectangles. Dimensions are bounded to 1e-9 through 1e6 μm; region
sizes have a 1e-12 μm minimum. This is a rectangular material map, not a general
mesh parser. Native `.str`, `.msh`, `.vtk`, and arbitrary solver output formats
are not accepted; no implicit solver conversion is performed.

Every imported record remains **Unverified imported data**, including files
whose source text claims otherwise. The filename, unverified source description,
and SHA-256 of the exact source bytes are displayed. If Web Crypto is unavailable,
the UI says the hash is unavailable. A hash does not validate the source, physics,
license, or numerical baseline. Raw files are not sent to the loopback service.

## Comparison rules

- Select at most two results of the same kind and units. No implicit conversion.
- Curves share axes. Absolute differences are computed only for identical sample
  coordinates and count. Different coordinates produce an overlay only, with an
  explicit no-interpolation notice.
- Imported structures appear side by side with a common scale and material color
  mapping. Region coordinates remain available in tables. Reference drawing zoom
  controls do not modify or simulate imported material maps.
- No tolerance, acceptance verdict, approved baseline, or validated-result export
  is inferred. Removing a record removes only the in-memory copy, not its file.

## Mock lifecycle

**Run reference workflow** drives a typed in-memory state machine. While running,
use **Simulate interruption**, **Recover mock run**, or **Cancel mock run**.
Project/deck/bias editing is locked while running or interrupted. Recovery keeps
the mock step; cancellation is terminal for that run. Event generations reject
stale timer events, and history retains the last 20 transitions.

This path never calls a solver or execution API, even on a local-service page.
It does not claim process-restart, OS-restart, or power-loss durability. Reloading
clears the mock. The existing explicit status connection remains status-only.

## Verification and deferred scope

`npm run test:m4` runs file-contract and UI tests; `npm run check` includes these
alongside the existing frontend and backend suites. UI tests cover both static
and local-bootstrap modes, keyboard/pointer actions, import replacement, invalid
files, comparison limits, and mock cancellation/recovery without network calls.

M4's independent implementation is available. Full native solver integration,
execution validation, and product activation remain deferred until M3 receives:

1. reviewed Windows/macOS/Linux × Docker/Podman qualification;
2. the required physical power-cut evidence;
3. approved solver rights, immutable images, SBOMs, and numerical corpus.

M4 does not modify M3 approval manifests, runtime grants, release profiles, or
the existing OpenTCAD social-preview image.
