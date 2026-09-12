# OpenTCAD

[한국어](README.ko.md) · [Try OpenTCAD](https://jtech-co.github.io/OpenTCAD/) · [Documentation](docs/README.md)

![OpenTCAD social preview](frontend/public/og.png)

OpenTCAD is an open-source semiconductor simulation workspace with an English and Korean web interface. Explore how device dimensions, doping and applied voltages affect electrical behavior, from an instant NMOS calculator to real local PN-junction and 2D MOSFET simulations.

## What can I do?

- Change NMOS parameters and immediately inspect calculated currents and I-V curves.
- Run real DEVSIM PN and 2D MOSFET templates locally and inspect potential, carrier and doping distributions.
- Connect supported SUPREM process results to device analysis through an experimental CLI workflow.
- Reopen, compare and export local results, or connect a trusted AI client through the optional local MCP bridge.

**[What is TCAD, and what can OpenTCAD simulate?](docs/en/simulation-guide.md)** explains the concepts, supported experiments, inputs, results and model limits.

## Get started

[Open the web app](https://jtech-co.github.io/OpenTCAD/) to use the calculator without installing a solver. English is the default; select **한국어** to switch languages.

To run the browser app locally, install Node.js 22/24 and npm 10+, then run:

```bash
npm ci
npm run dev
```

Real simulations require separately installed solvers and the local service:

- [Windows setup, saved jobs and backup](docs/en/windows-mvp.md)
- [Experimental laboratory setup for Windows, macOS and Linux](docs/en/mvp-laboratory.md)
- [All guides, including SUPREM and MCP](docs/README.md)

## Current scope

OpenTCAD is a Windows-first local MVP candidate for education and numerical experimentation. GitHub Pages runs the analytical calculator and reference views, not native solvers. Local solves use supported fixed templates; they are not instantaneous or a general-purpose process editor. Other-platform product qualification remains incomplete.

Results are not calibrated fabrication sign-off or a replacement for physical measurements. See the [simulation guide](docs/en/simulation-guide.md) and [release scope](docs/en/product-scope.md).

## License

Original OpenTCAD code and documentation use the [MIT License](LICENSE). Solvers are installed separately and retain their own terms. See [licensing and notices](docs/en/licensing.md).

Copyright © 2026 JTech-CO.
