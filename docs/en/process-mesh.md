# Original SUPREM mesh and electrodes

[한국어](../ko/process-mesh.md) · [Installation and model](mos-process.md)

The experimental `suprem-mesh` mode preserves the process's silicon and oxide
triangles, interfaces and active nodal doping. It does not interpolate onto the
default rectangular device. Source, drain, body and gate are supplied as explicit
exterior edges in a separate JSON file bound to the exact STR SHA-256.

## Generate and connect a supported process

Use an already installed, trusted SUPREM image with the layout described in the
[process guide](mos-process.md). No image is downloaded or redistributed. These
commands run from the repository in an environment where Python and Podman work:

```bash
python -m backend.app.experimental.suprem_container --enable-experimental-suprem --runtime podman --image sha256:YOUR_64_HEX_LOCAL_IMAGE_ID --output /absolute/new-run --gate-oxide-nm 10
python -m backend.app.experimental.process_mesh /absolute/new-run/process.str --output /absolute/new-run/contacts.json --gate-length 1 --oxide-nm 10
```

`--gate-oxide-nm` adds a **deposited and etched** dielectric after the implant and
anneal; it does not claim thermal oxidation. Omitting it preserves the previous
bare-silicon recipe. `--lateral-refinement 2` halves initial x spacing, leaving y
spacing unchanged. This reruns the process on a finer mesh, not just the device
solve. Limits on parsed STR points/triangles still apply, so large cases may fail.
The same options are available for the explicit native SUPREM CLI.

The contact generator is specific to this declared rectangular recipe, not an
electrode inference system. It selects source/drain top edges outside the gate,
the silicon backside and the oxide top. It rejects missing or ambiguous chains.
Inspect its result before using a different recipe. Files are created exclusively;
existing process directories and contact files are never overwritten by these CLIs.

For Windows with the existing Debian/Podman environment, prefix the process command
with `wsl.exe -d Debian -- python3` instead of `python`. Then use the Windows pinned
DEVSIM environment for the contact generator and laboratory. All generated files
are local. The previously observed source image is not a product-approved release.

```bash
npm run local:lab -- --suprem-structure /absolute/new-run/process.str --suprem-contacts /absolute/new-run/contacts.json
```

In the 2D panel, choose **Original SUPREM mesh and contacts**. Only device width,
gate voltage and drain voltage remain editable. Geometry, doping and mesh spacing
come from the process file. For backward-compatible input records, template-only
fields remain in JSON but are unused in this mode. The map uses actual imported
coordinates and assigned electrode segments, with separately scaled x/y axes.
The service snapshots both files at startup and accepts no file paths or decks
through HTTP. A contact file without a structure causes startup to fail.

## Contact contract and safety checks

The file has exactly `format: "opentcad-suprem-contacts"`, `schemaVersion: 1`,
`sourceSha256`, and `contacts`. Contacts contains exactly `source`, `drain`, `body`
and `gate`; each has an integer STR `region` ID and an `edges` array. Each edge is
a pair of original **1-based STR point IDs**, not a DEVSIM node index. The format
permits curved boundaries represented by existing edges, but does not split edges.

The supported mesh has exactly one connected silicon region and one connected
oxide region with a shared conforming interface. Unsupported materials, additional
regions, duplicate coordinates/triangles, folded or degenerate cells, nonmanifold
edges, crossings, T-junctions and disconnected interfaces/regions are rejected.
Each contact must be a connected open exterior-edge chain on the correct material.
Contacts cannot share nodes with each other or with the silicon/oxide interface.
Source/drain nodes must have positive net doping, body nodes negative net doping,
and at least part of the interface must be p-type. These are structural checks,
not proof of a calibrated or physically suitable MOS device.

The transfer preserves source triangles, converts micrometres to centimetres for
DEVSIM, assigns doping at original silicon nodes without interpolation, and binds
potential continuity to the imported interface. The oxide top contact is an ideal
metal boundary with the existing +0.45 V offset, not a solved polysilicon region.
Output checks compare triangle coordinates/connectivity up to roundoff and region
areas/counts. The result fingerprints the structure, contact manifest and mesh.
The M3 approval gates, solver licensing boundaries and OG image are unchanged.

## Replay and evidence

```bash
python -m backend.app.experimental.replay opentcad-mos-result.json --suprem-structure /absolute/new-run/process.str --suprem-contacts /absolute/new-run/contacts.json
npm run test:mvp:solver
```

Replay requires the same structure and contact hashes, template source fingerprint,
inputs and solver version. It compares numeric fields, geometry and contacts;
changing a terminal assignment cannot silently reuse old results. Older result
records require their matching source revision for strict replay.

The native suite tests equivalent synthetic template/original-mesh solves, gate
response, exact nodal transfer, repeatability and unsafe-contact rejection on
Windows, macOS and Linux. Synthetic fixtures are explicitly not SUPREM execution
evidence. A separate real Podman SUPREM observation preserved 3,400 silicon and 80
oxide triangles, producing approximately 115.762 uA at VG=1 V, VD=0.1 V and W=10 um.
Lateral process-mesh refinement produced 115.528 uA, about a 0.203% difference.
That comparison includes process discretization changes and is not a global error
bound or a calibrated numerical corpus approval.
The [local observation record](../../validation/experimental/process-mesh-observation.json)
contains source/result hashes and authenticated HTTP, replay and frontend-decoder checks.

Remaining limits: multiple silicon/oxide regions, polysilicon/metal/nitride stacks,
general electrode inference, mesh repair and product-qualified process accuracy.
GitHub Pages still cannot execute native solvers; source changes need a separate
`main` merge/deployment to appear on the public site.
