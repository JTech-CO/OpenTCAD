# 2D MOSFET and SUPREM coupling

[한국어](../ko/mos-process.md) · [Laboratory installation](mvp-laboratory.md)

## What actually runs

The opt-in local laboratory now solves a **2D NMOS**, not a rendered 1D result.
Install the pinned DEVSIM requirements, build, then run `npm run local:lab`.
In **2D MOSFET simulation**, edit inputs and press **Run 2D MOSFET**. The output
contains a drain-voltage sweep and real silicon/oxide triangle connectivity,
potential, electron/hole density and net doping. Select the displayed field or
show the mesh. Input changes clear old results until a new solve completes.
The static GitHub Pages build displays controls but cannot run native solvers.

The browser calculator, 1D PN solver and 2D solver are distinct models. Only one
native job runs at a time across both solver panels. Cancel terminates and reaps
the child; a failed HTTP request alone does not mean the job was cancelled.
History remains session-local (32 jobs), so save results before reloading.

## Model and numerical scope

`devsim-mos-2d-300K-v1` uses Poisson and electron/hole drift-diffusion with SRH
recombination through DEVSIM's `simple_physics` helpers. It uses Boltzmann carrier
statistics, fixed 300 K, ni=1e10 cm^-3, electron/hole mobility 400/200 cm²/Vs,
1 microsecond lifetime, silicon permittivity 11.7 epsilon0 and oxide 3.9 epsilon0.
Metal gate potential is VG + 0.45 V relative to intrinsic silicon. Source/body
are at zero applied bias; source, drain and body contacts are ideal ohmic contacts.
The dielectric has continuous potential/displacement at the silicon interface
and no carrier transport. Uncontacted outer boundaries are insulating.

Gate length is 0.5 to 2 micrometres; each source/drain extension is 0.5 micrometres;
silicon depth is 0.5 micrometres. Width is 1 to 100 micrometres, oxide 5 to 30 nm,
VG 0 to 1.5 V, VD 0 to 0.5 V. Template doping is a p-type substrate with smooth
Gaussian donor tails beneath source/drain (50 nm lateral, 70 nm vertical scale).
Refinement 2 halves silicon mesh spacing. Contacts are 0.1 micrometres away from
the gate edge. 2D current in A/cm is multiplied by width in cm to report amperes.
The map enlarges the vertical scale and uses vertex-averaged triangle colors;
it is a field visualization, not an exact-aspect fabrication drawing.

There is no high-field mobility, quantum correction, Fermi-Dirac degeneracy,
impact ionization, tunneling or process-calibrated model. Some bounded combinations
can fail to converge. Failure never falls back to analytical or reference output.
Imported high-concentration profiles especially require physical-model review.

`npm run test:mvp:solver` exercises real native solves. The default Windows case
(L=1 um, W=10 um, tox=10 nm, VG=1 V, VD=0.1 V) produced approximately 105.174 uA.
The coarse/fine drain-current difference was 1.0123%; the acceptance ceiling is
10% for this educational case, not a universal error bound. Tests also require
gate response, linear width scaling, near-zero equilibrium current, monotonic
drain current, positive carriers, current conservation, cancellation and replay.
At every drain step, |IS+ID+IB| <= 1e-13 A + 1e-5 max(|terminal current|).
The Windows/macOS/Linux CI suite runs these tests but does not grant M3 approval.

## SUPREM process path

Two independent pieces are provided: a fixed-deck process CLI and a strict import
of an existing SUPREM-IV.GS B.9305 2D `.str` file. Neither redistributes the solver.
Docker was not reachable on the development host, but an existing SUPREM reference
image was available in Debian WSL's Podman. **The generated deck and actual coupling
were executed there.** A repeated process produced identical STR bytes; doubling
implant dose from 1e14 to 2e14 cm^-2 changed the final 2D drain current from about
115.549 to 119.221 uA. Replaying the original solve with the repeated STR reproduced
the result. This is a local, non-baseline observation, not a calibrated process
accuracy claim or M3 approval. The separate synthetic STR tests are not process evidence.

The authenticated loopback HTTP job route was also exercised with this actual
process profile. [Recorded observation](../../validation/experimental/mos-process-observation.json)
contains image/input hashes and numeric outcomes without distributing the solver.

For an already installed image with the `/opt/suprem4gs` layout, use the container
CLI (Python standard library only). No image is pulled or distributed:

```bash
python -m backend.app.experimental.suprem_container --enable-experimental-suprem --runtime podman --image sha256:YOUR_LOCAL_IMAGE_ID --output /absolute/path/new-process-run
```

Use the full 64-hex local image ID, not a mutable tag. `docker` is also an adapter
option but was not exercised in this observation. The container has no network,
no host mounts, a read-only root, unprivileged UID, dropped capabilities and bounded
CPU, memory, process count and tmpfs. Temporary per-run containers are removed and
absence checked. No M3 production adapter or gate is invoked. On this Windows host,
run this command with `wsl.exe -d Debian -- python3 ...` from the project directory;
the resulting STR can then be read by the Windows DEVSIM laboratory. The cached
image itself remains subject to the unresolved M3 redistribution approvals.

With a trusted, legally usable native SUPREM installation, on the OS where that
binary actually runs, use the same Python environment as the laboratory:

```bash
python -m backend.app.experimental.suprem_process --enable-experimental-suprem --executable /absolute/path/suprem --data-directory /absolute/path/data --output /absolute/path/new-process-run --gate-length 1 --dose 1e14 --energy 30 --minutes 10 --temperature 950
```

This CLI deposits and removes an implant mask, implants phosphorus, then anneals
a boron-doped rectangular substrate. Dose is cm^-2, energy keV, time minutes,
temperature Celsius. It does not model a complete fabrication sequence or grow
the gate oxide. The DEVSIM template supplies that dielectric. The CLI passes only
code-owned commands and bounded numbers, never an uploaded deck. It checks exit
status and parses output before writing `process.str`, `process.in`, and provenance
JSON in a **new** directory. It fingerprints executable, data and deck, with a
120-second deadline and bounded captured diagnostics. A failed run may leave an
empty output directory. This explicit CLI is **not an OS sandbox** and must not
be exposed to remote clients. Native Windows support is not implied by an ELF
binary; run the process CLI inside its compatible Linux/WSL environment if needed.

Then snapshot the resulting structure at service startup:

```bash
python -m backend.app.experimental.suprem /absolute/path/process.str
npm run local:lab -- --suprem-structure /absolute/path/process.str
```

Choose **Imported SUPREM active doping** in the 2D panel. Match gate length to the
process deck; the file must cover every silicon node of the template. Imported
doping replaces substrate/donor form values; those controls are disabled. The
server holds an immutable in-memory snapshot until restart. No path is accepted
through HTTP and no browser deck is executed. Imported provenance says
`processSimulated: false`: the importing service did not itself run or attest the
SUPREM process. A source file hash proves bytes, not authorship or accuracy.

Transfer is limited to active dopants, **not full process geometry/contact import**:

- STR coordinates are micrometres; `c` IDs are 1-based, `n` point IDs 0-based.
- Material comes from `r`; silicon is material 3. Interface values are selected
  by point and material, never by region number or column position.
- The `s` species list controls columns. Active As/P/Sb codes 20/21/22 minus active
  B code 23 define net doping. Chemical concentrations and code 24 are not used
  as substitutes. Unknown species/materials and missing active columns fail.
- Silicon triangle interpolation is linear in concentration, without extrapolation.
  Missing coverage, degenerate/duplicate cells, conflicting overlaps, wrong NMOS
  contact/body/channel polarity and non-finite data fail. This is not conservative
  dose remapping or a general-purpose malformed-mesh validator.
- Only B.9305 2D silicon/oxide/poly files are accepted, up to 1 MiB, 4000 points
  and 8000 triangles. Other versions and 1D process profiles need explicit adapters.

Format reference: [upstream STR description at the recorded source revision](https://github.com/ypooh2042/tcad-webapp/blob/13bce4a9daba5796ceee633fb8cd0c870465f766/SUPREM4GS/STR_FILE_FORMAT.md).
DEVSIM mesh API: [official meshing guide](https://devsim.net/meshing.html).
Our parser, mesh generator and deck generator are repository code; no upstream
SUPREM binary, example deck or patch bundle is copied into the deliverable.
User-installed DEVSIM helpers retain their Apache-2.0 license; SUPREM usage and
redistribution rights require separate review.

## Replay and remaining work

Save the 2D JSON from the panel, then recompute in the pinned environment:

```bash
python -m backend.app.experimental.replay opentcad-mos-result.json
python -m backend.app.experimental.replay opentcad-mos-result.json --suprem-structure /absolute/path/process.str
```

Replay checks the record hash, input, template source fingerprint, solver version,
process source hash, connectivity and numeric fields. Relative tolerance is 1e-7;
absolute tolerances are reported, including 1e-12 A for I-V current. Byte identity
is reported separately and is not promised across native sparse solvers. Hashes
are integrity checks, not signatures or validation certificates.

Still pending: cross-platform SUPREM qualification, full process-shaped mesh and contact
transfer, calibrated MOS benchmarks, product-approved solver images/licenses,
M3 runtime qualifications and physical power-loss qualification. The new code
does not promote any existing evidence gate or alter the OpenTCAD OG image.
