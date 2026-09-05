# Device laboratory MVP

[한국어](../ko/mvp-laboratory.md)

The laboratory implements three user-facing acceptance criteria within a deliberately
limited educational scope: immediate NMOS calculation, actual local DEVSIM PN-junction
simulation, and numerical checks with replayable result records. It is not the full
SUPREM-IV.GS-to-DEVSIM process/device product. M3 activation, image redistribution,
physical power-loss qualification, and the approved numerical corpus remain unchanged.

The optional DEVSIM package and its helpers are Apache-2.0; their authoritative
LICENSE and NOTICE ship with the upstream package. NumPy and Windows MKL/runtime
dependencies retain their own installed license notices. No solver source or binary
is vendored here. The ignored local environment is neither relicensed under OpenTCAD's
MIT license nor approved for M3 redistribution. The frozen M0 dependency inventory
is unchanged; the experimental requirements are a separate, opt-in dependency set.

## Start calculating

Use Node.js 22 or 24 and npm 10+. Run `npm ci`, then `npm run dev`, and open the URL
printed by the server. Choose **Open device laboratory**, or use `#lab` directly.
The same calculator works in the GitHub Pages static build, without Python or Docker.
The public site follows `main`; development-branch code is not automatically deployed.

Edit channel length/width, oxide thickness, body doping, mobility, flat-band voltage,
VGS, VDS, or VSB. Current, threshold, transconductance, I-V curves and the schematic
are recalculated from those inputs. Invalid inputs clear the calculation rather than
leaving an apparently current plot. Geometry is a labeled schematic, not a solved mesh.

The fixed model `long-channel-nmos-300K-v1` uses SI internally, a 300 K temperature,
ni = 1e10 cm^-3, silicon relative permittivity 11.7 and oxide relative permittivity 3.9.
Its threshold is VFB + 2φF + γ√(2φF + VSB), with φF = kT/q ln(NA/ni).
Drain current uses the long-channel strong-inversion square law; gm is its gate-voltage
derivative. There is no subthreshold conduction, short-channel or quantum correction,
channel-length modulation, mobility degradation, temperature sweep or process calibration.
An externally supplied mobility is constant across the sweep, not derived from doping.
See [MIT's MOSFET/GCA lecture](https://ocw.mit.edu/courses/6-012-microelectronic-devices-and-circuits-fall-2009/resources/mit6_012f09_lec10/)
for the underlying approximation.

## Install the opt-in local solver

Use 64-bit Python 3.12 to 3.14. Python 3.12 is used in the laboratory CI.
Create the environment in this repository. These commands install third-party packages
from PyPI, not OpenTCAD-approved OCI solver images. Review their upstream terms.

Windows PowerShell:

```powershell
python -m venv .venv-mvp
.\.venv-mvp\Scripts\python.exe -m pip install -r backend/app/experimental/requirements.txt
npm ci
npm run build
npm run test:mvp:solver
npm run local:lab
```

macOS / Linux:

```bash
python3 -m venv .venv-mvp
.venv-mvp/bin/python -m pip install -r backend/app/experimental/requirements.txt
npm ci
npm run build
npm run test:mvp:solver
npm run local:lab
```

The command uses `.venv-mvp` unless `OPENTCAD_LAB_PYTHON` specifies another interpreter.
DEVSIM is pinned to 2.11.0. On Windows, the requirements also pin MKL and its runtime
dependencies; the launcher resolves the environment's DLL directory, including when
the repository path contains Korean characters. A missing compiler runtime or platform
wheel must be resolved using [DEVSIM's installation guide](https://github.com/devsim/devsim/blob/main/INSTALL.md).
There is no silent analytical or mocked substitute if DEVSIM fails to load.

Open the **complete URL printed by `local:lab`**, not the Vite URL. It contains a private
per-launch capability in its fragment. The page consumes and removes the fragment;
do not share the original URL. Reopen that original URL after a reload if you need
to reconnect. Stop the server with Ctrl+C. Startup performs an actual equilibrium
solve before announcing readiness. `local:serve` remains the separate gated M3 command.

## Run and inspect a PN junction

Set length, acceptor/donor concentration, area, final forward voltage and mesh count.
Click **Run DEVSIM solve**. This submits numerical inputs to an authenticated loopback
API, starts a bounded native solver process, polls its status, then displays current,
potential, electron/hole density and a spatial color map of the computed 1D potential.
It is a 1D map, not an inferred 2D simulation. The independent NMOS calculator is not
a DEVSIM MOSFET template, and the process deck editor does not feed this solver.

The PN template solves Poisson and electron/hole continuity equations using DEVSIM's
`simple_physics` helpers, with ideal ohmic contacts and SRH recombination. The p region
occupies x < L/2; the n region includes the midpoint. The area scales 1D current density
from A/cm² to A. Parameters are: 300 K, ni = 1e10 cm^-3, μn = 400 and μp = 200 cm²/Vs,
both lifetimes 1 μs, εSi = 11.7 ε0. Bias ramps from zero in increments no larger than
0.025 V. Inputs are limited to L = 1..10 μm, doping = 1e15..1e17 cm^-3,
area = 1..100 μm², final forward bias = 0..0.5 V and 100/200/400 mesh intervals.
These are admission bounds, not a claim that every corner is converged or validated.
The model excludes avalanche, self-heating, tunneling, degenerate statistics and
process-derived doping. See [DEVSIM's PN example](https://github.com/devsim/devsim/blob/main/examples/diode/diode_1d.py).

Inputs are locked during a run. Cancel terminates and reaps the child process.
Each process has a 60-second deadline and a 2 MiB diagnostic/output limit; one solve
can run at a time. The service retains at most 32 jobs until restart. A failed solve
has no success result. Communication failure is not proof of cancellation: use Cancel
or Recheck status. This is not an OS sandbox, durable broker or restart-safe job service.
Only code-owned templates run; no submitted deck, Python, shell command or path is accepted.
The API inherits the existing loopback peer, Host, Origin, bearer and request-size checks.

## Save, reload and reproduce

**Save inputs and results** downloads a JSON record. Neither calculation nor solver
records contain API tokens. Browser drafts are not autosaved; save before navigating
away or reloading. **Load calculation inputs** stages the stored input for explicit
replacement. It does not trust or display a saved result as a fresh calculation.
Run DEVSIM again to recompute an imported PN record.

Solver records contain the input, constants, units, template SHA-256, solver version,
OS/Python identifiers, input SHA-256, numerical arrays, per-run checks and result SHA-256.
Hashes identify content, not authorship, physical accuracy or product approval.
Replay a saved record from this repository (use the matching virtualenv interpreter):

```bash
python -m backend.app.experimental.replay path/to/opentcad-pn-result.json
```

Replay verifies record integrity, matches template/version/inputs, runs the real solver
and compares arrays. The report distinguishes exact record equality from numerical
agreement (relative 1e-8 plus explicit per-field absolute tolerances). A template change
requires a new result, not silent acceptance of the old baseline.

## Acceptance checks and remaining limits

- `npm run test:mvp`: analytical benchmark, continuity, dimensional scaling, body effect,
  input-to-output UI behavior, invalid inputs, local transport and result contracts.
- `npm run test:mvp:solver`: real native solves, authenticated HTTP end-to-end execution,
  cancellation, timeout cleanup, repeated-result hashes, file replay, mass action at
  equilibrium, area scaling, doping response, current conservation and mesh refinement.
- `npm run check`: regression suite, including the dependency-free laboratory API tests.
  Native solver tests are opt-in locally and mandatory in the separate laboratory CI.

The default 2 μm junction benchmark checks the 200/400-interval current difference is
below 2% and smaller than the 100/400 difference. Ohmic equilibrium boundary voltage
must match kT/q ln(NA ND/ni²) within 1e-7 V. At every bias, contact-current imbalance
must be below 1e-8 A/cm² + 1e-5 times the larger contact current density. The recorded
`maxCurrentToleranceRatio` must not exceed 1. These tests validate this limited model
and implementation, not experimental silicon accuracy or an approved M3 corpus.

The initial Windows run measured about 0.104% current change for 200 versus 400 intervals
and a 5.2e-14 V equilibrium-boundary error; repeated runs produced identical result hashes.
CI separately runs the numerical tests on Windows, macOS and Linux. Those jobs do not
grant Docker/Podman runtime qualification or physical power-loss approval.
