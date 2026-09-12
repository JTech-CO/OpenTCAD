# TCAD and simulations in OpenTCAD

[한국어](../ko/simulation-guide.md) · [OpenTCAD](../../README.md) · [Documentation](../README.md)

## What is TCAD?

TCAD means **Technology Computer-Aided Design**. It uses physical models to study semiconductor manufacturing processes and the behavior of the resulting devices. Instead of manufacturing a new sample for every idea, a simulation lets you change a model's inputs and inspect its predicted behavior.

There are two related questions:

- **Process simulation:** how does a fabrication recipe change material regions and dopant distributions?
- **Device simulation:** given a structure, materials, doping and electrical contacts, what currents and internal distributions result from applied voltages?

A device solver divides the structure into a **mesh**, then solves equations at that discretization. DEVSIM uses a finite-volume method for partial differential equations; see its [official introduction](https://devsim.org/introduction.html). A finer mesh can help assess discretization error, but cannot fix missing physical models.

TCAD is not merely a 2D drawing tool. Nor is it the same as a SPICE circuit simulator: OpenTCAD's current experiments concern individual devices, not a connected circuit or a chip layout.

## Choose the right experiment

| Feature | Inputs you change | Results | Where it runs |
|---|---|---|---|
| Analytical NMOS calculator | Geometry, body doping, mobility and voltages | Current, threshold, transconductance and I-V curves | Browser, including GitHub Pages |
| 1D PN junction | Length, p/n doping, area, forward bias and mesh | I-V, potential and electron/hole distributions | Local DEVSIM |
| 2D NMOS template | Gate length, oxide thickness, width, doping, bias and refinement | Drain I-V and triangular-mesh potential/carrier/doping maps | Local DEVSIM |
| SUPREM-to-device experiment | Supported implant/anneal recipe; optional deposited dielectric | Process structure and its effect on a subsequent 2D device solve | Separate local SUPREM CLI, then DEVSIM |
| Reference workspace | Illustrative project, bias and imported data | Reference drawings and comparison of supplied data | Browser, without solver execution |

These are different calculation paths, not different views of a single solver. The calculator updates immediately. Native solvers run only after an explicit submission and may take time or fail to converge. Displaying a stored result does not run a new simulation.

## 1. Instant NMOS calculator

An NMOS transistor uses its **gate** voltage to control current between **source** and **drain**. The gate oxide separates the gate from the semiconductor; the **body** is the substrate region.

Change channel length and width, oxide thickness, body doping, mobility, flat-band voltage, gate-source voltage VGS, drain-source voltage VDS or body bias VSB. OpenTCAD recalculates the schematic, I-V curves, threshold voltage and transconductance.

- **Threshold voltage:** the model's onset of strong inversion.
- **Drain current:** current predicted for the selected voltages and geometry.
- **Transconductance (gm):** how sensitively current responds to gate voltage.

Try increasing width while holding the other inputs fixed. In this model, current scales with width. Then change oxide thickness or body bias and inspect the threshold and curves. These are controlled model experiments, not measured silicon results.

The calculator is a 300 K, long-channel, strong-inversion square-law approximation. It does not solve a spatial mesh. It omits subthreshold conduction, short-channel effects, channel-length modulation, quantum corrections and temperature sweeps. Its below-threshold current is an idealization, not a leakage prediction.

[Calculator details and setup](mvp-laboratory.md)

## 2. PN-junction device simulation

A PN junction joins p-type and n-type semiconductor regions. The local template solves for potential and charge-carrier transport along one spatial direction. A colored display of those values is still **1D data**, not a 2D device solve.

Set junction length, acceptor and donor concentrations, cross-sectional area, final forward bias and mesh count. Run DEVSIM to obtain a forward I-V sweep and potential, electron and hole profiles.

Supported admission ranges are 1-10 μm length, 1e15-1e17 cm^-3 doping on each side, 1-100 μm² area, 0-0.5 V final forward bias and 100/200/400 mesh intervals. The model uses 300 K, ideal ohmic contacts, Poisson and electron/hole continuity equations, constant mobilities and SRH recombination.

A useful experiment is to compare two areas with all other parameters unchanged. Then compare 200 and 400 mesh intervals to see whether the calculated current is stable under refinement. Run each case explicitly and keep its result file.

This template does not model reverse-breakdown behavior, tunneling, self-heating or process-imported junction doping. Valid input bounds do not guarantee convergence at every combination.

[PN operation, model constants and replay](mvp-laboratory.md)

## 3. Real 2D MOSFET simulation

The local 2D template solves a silicon/oxide NMOS cross-section on a triangular mesh. It is not an analytical curve placed over an illustration.

For the default template, change gate length, oxide thickness, device width, body/source-drain doping, gate voltage, final drain voltage and mesh refinement. Inspect:

- drain current versus drain voltage;
- electrostatic potential in the cross-section;
- electron and hole concentrations;
- net doping, mesh and electrode locations.

The template supports gate lengths of 0.5-2 μm, widths of 1-100 μm, oxides of 5-30 nm, gate bias of 0-1.5 V and drain bias of 0-0.5 V. Source and body are held at zero. Temperature is fixed at 300 K.

Start with the default case, save its result, change gate voltage and run again. Compare the current and channel carrier distribution. A drain-voltage sweep is part of a solve; a series of different gate voltages requires separate submissions. Try mesh refinement before interpreting a small difference as a physical effect.

The transport model uses Poisson and drift-diffusion equations with SRH recombination and constant mobilities. It excludes high-field mobility, quantum corrections, degenerate statistics, impact ionization and tunneling. It is not a validated model for nanoscale FinFETs or arbitrary materials. Width scales the 2D terminal current; it does not make the calculation 3D. Plot axes may be scaled separately for readability.

[2D model, operating ranges and numerical checks](mos-process.md)

## 4. SUPREM process-to-device experiments

This advanced, experimental path asks: **if the process recipe changes the dopant distribution, how does the resulting device current change?**

It currently requires an explicitly enabled fixed-recipe CLI and a separately installed, trusted SUPREM installation or compatible local container image. It is not a browser process-deck execution service.

1. Run the supported masked implantation and anneal recipe, changing quantities such as dose, energy, anneal time and temperature.
2. Keep the generated structure and provenance files.
3. Start the local device service with the chosen structure, and contacts when needed.
4. Select the corresponding import mode in the 2D panel and run DEVSIM.
5. Repeat explicitly for a different process recipe and compare results.

Two transfer modes serve different purposes:

- **Active-doping import:** interpolate supported active dopant fields onto the default device's silicon mesh. This does not preserve the original process geometry.
- **Original mesh and contacts:** preserve supported silicon/oxide triangles and nodal doping, with explicit electrode edges tied to the structure's hash. Geometry and doping then come from the file; only width and gate/drain voltages remain editable.

The bare-silicon recipe does not grow a gate oxide. The optional dielectric recipe deposits and etches oxide; it is not thermal oxidation. Unsupported structures are rejected instead of silently repaired. General multilayer process editing, arbitrary electrode inference and a fully graphical process-to-device pipeline are not implemented.

The service snapshots process files at startup. Changing a process file on disk does not automatically recompute or reload the device.

[Process CLI and doping transfer](mos-process.md) · [Original mesh and contacts](process-mesh.md)

## Read results responsibly

- Check the **source label**: analytical estimate, real DEVSIM output, saved result, unverified import or reference data.
- **I-V** means current as a function of applied voltage; **bias** means the imposed terminal voltage.
- **Doping** describes donor/acceptor concentrations; **carriers** are electrons and holes computed by the device model. They are not interchangeable.
- Check units: dimensions may use μm or nm, concentration cm^-3 and current A. Current density is not terminal current.
- Check convergence, current conservation and refinement behavior, not just whether the graph looks smooth.
- Match model, geometry, units and input conditions before comparing results. A difference is not automatically an error or an improvement.

The [reference workspace](m4-workspace.md) supports illustrative projects and data inspection. Editing its deck does not run SUPREM, and editing its bias does not recompute its reference curves. Its mock execution/recovery controls do not describe a real solver job.

## Save, reproduce and automate

The Windows local MVP can reopen stored PN/2D results, compare compatible final currents and export result JSON. It provides offline checksum backup/restore and interruption classification after a service restart. It retains at most 32 jobs per state directory; see [Windows operation](windows-mvp.md) before reaching that limit.

For a repeatable experiment, preserve inputs, result JSON, the matching OpenTCAD revision, solver version and any imported process/contact files. Replay checks content and compares numerical fields with declared tolerances. Matching hashes are evidence of matching content, not physical accuracy or authorship.

The optional [local MCP bridge](mcp.md) lets a trusted client inspect capabilities and results. Submission/cancellation require explicit enablement. A sweep plan validates up to eight variants but does not automatically queue or execute them. AI can help coordinate experiments; it is not a replacement for the solver or numerical verification.

## What OpenTCAD does not currently promise

The current scope is education and numerical experimentation, with a Windows-first local MVP candidate and experimental installation paths for other systems. It is not a fabrication sign-off tool, calibrated instrument, general 3D device suite, circuit simulator, hosted multi-user solver or one-click bundled-solver installer. OpenTCAD does not currently expose AC/transient simulation or arbitrary new device/physics definitions through its UI, even where the underlying solver has broader capabilities.

The static website runs the calculator, not native SUPREM or DEVSIM. Physical power-cut certification and independent institutions are not required for the ordinary release scope, but neither are they claimed. Read the [release scope](product-scope.md) and [licensing](licensing.md) before distributing or extending the application.
