"""Fixed 1D PN drift-diffusion template using DEVSIM's Apache-2.0 helpers.

No submitted code is evaluated. All expression strings are code-owned. See
docs/en/mvp-laboratory.md for constants, limits and upstream references.
"""
import hashlib
import ctypes.util
import importlib.metadata
import math
import os
from pathlib import Path
import platform
import sys

from .contract import MODEL, canonical, digest, strict_json, validate_input

Q = 1.602176634e-19
KB = 1.380649e-23
EPS = 11.7 * 8.8541878128e-14  # F/cm
VT = KB * 300 / Q
_dll_handles = []

def load_devsim():
    if importlib.metadata.version("devsim") != "2.11.0":
        raise RuntimeError("unsupported-devsim-version")
    if sys.platform == "win32":
        directory = Path(sys.prefix) / "Library" / "bin"
        if (directory / "mkl_rt.2.dll").is_file():
            _dll_handles.append(os.add_dll_directory(str(directory)))
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            # Use the DLL name: DEVSIM's loader cannot handle every Unicode path.
            os.environ["DEVSIM_MATH_LIBS"] = "mkl_rt.2.dll"
    elif sys.platform.startswith("linux"):
        library = ctypes.util.find_library("openblas")
        if not library:
            raise RuntimeError("Install the system OpenBLAS shared library")
        os.environ["DEVSIM_MATH_LIBS"] = library
    import devsim
    return devsim

def solve_pn(value):
    p = validate_input(value)
    ds = load_devsim()
    from devsim.python_packages import simple_physics as physics
    from devsim.python_packages.model_create import CreateSolution
    # Every job already starts in a fresh process. reset_devsim would erase the
    # UMFPACK callback registered during import on Linux/macOS.
    device, region, mesh = "pn", "silicon", "pn_mesh"
    length = p["lengthUm"] * 1e-4
    ds.create_1d_mesh(mesh=mesh)
    for i in range(p["intervals"] + 1):
        ds.add_1d_mesh_line(mesh=mesh, pos=length * i / p["intervals"], ps=length / p["intervals"], tag=f"n{i}")
    for name, tag in (("anode", "n0"), ("cathode", f'n{p["intervals"]}')):
        ds.add_1d_contact(mesh=mesh, name=name, tag=tag, material="metal")
    ds.add_1d_region(mesh=mesh, material="Si", region=region, tag1="n0", tag2=f'n{p["intervals"]}')
    ds.finalize_mesh(mesh=mesh)
    ds.create_device(mesh=mesh, device=device)
    physics.SetSiliconParameters(device, region, 300)
    for name, value in {"Permittivity": EPS, "ElectronCharge": Q, "kT": KB * 300,
                        "V_t": VT, "mu_n": 400, "mu_p": 200, "taun": 1e-6, "taup": 1e-6,
                        "acceptors": p["acceptorsCm3"], "donors": p["donorsCm3"], "junction": length / 2}.items():
        ds.set_parameter(device=device, region=region, name=name, value=value)
    ds.node_model(device=device, region=region, name="NetDoping", equation="ifelse(x < junction, -acceptors, donors)")
    physics.CreateSiliconPotentialOnly(device, region)
    for contact in ("anode", "cathode"):
        ds.set_parameter(device=device, name=physics.GetContactBiasName(contact), value=0)
        physics.CreateSiliconPotentialOnlyContact(device, region, contact)
    ds.solve(type="dc", absolute_error=1e-10, relative_error=1e-10, maximum_iterations=100)
    for name, initial in (("Electrons", "IntrinsicElectrons"), ("Holes", "IntrinsicHoles")):
        CreateSolution(device, region, name)
        ds.set_node_values(device=device, region=region, name=name, init_from=initial)
    physics.CreateSiliconDriftDiffusion(device, region)
    for contact in ("anode", "cathode"):
        physics.CreateSiliconDriftDiffusionAtContact(device, region, contact)
    def solve():
        ds.solve(type="dc", absolute_error=1e6, relative_error=1e-10, maximum_iterations=100)
    def nodes(name):
        return list(ds.get_node_model_values(device=device, region=region, name=name))
    def current(contact):
        return sum(ds.get_contact_current(device=device, contact=contact, equation=name)
                   for name in ("ElectronContinuityEquation", "HoleContinuityEquation"))
    solve()
    equilibrium = nodes("Potential")
    area_cm2 = p["areaUm2"] * 1e-8
    iv, balance = [], []
    # Fixed 0.025 V maximum bias increments; includes both endpoints.
    count = max(1, math.ceil(p["voltageV"] / 0.025))
    for index in range(count + 1):
        voltage = p["voltageV"] * index / count
        ds.set_parameter(device=device, name=physics.GetContactBiasName("anode"), value=voltage)
        solve()
        left, right = current("anode"), current("cathode")
        iv.append([voltage, left * area_cm2])
        balance.append(abs(left + right) / (1e-8 + max(abs(left), abs(right)) * 1e-5))
        if abs(left + right) > 1e-8 + max(abs(left), abs(right)) * 1e-5:
            raise RuntimeError("current-conservation-failed")
    x = [value * 1e4 for value in nodes("x")]
    potential, electrons, holes = nodes("Potential"), nodes("Electrons"), nodes("Holes")
    if not all(math.isfinite(v) for series in (potential, electrons, holes) for v in series) or min(electrons + holes) <= 0:
        raise RuntimeError("nonphysical-result")
    # Ohmic-contact equilibrium voltage is an independent analytic boundary check.
    expected = VT * math.log(p["acceptorsCm3"] * p["donorsCm3"] / 1e20)
    actual = equilibrium[-1] - equilibrium[0]
    result = {"format": "opentcad-solver-result", "schemaVersion": 1, "model": MODEL, "input": p,
              "inputSha256": digest(p), "solver": "DEVSIM", "solverVersion": importlib.metadata.version("devsim"),
              "templateSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "environment": {"python": platform.python_version(), "os": platform.system(), "machine": platform.machine()},
              "constants": {"temperatureK": 300, "niCm3": 1e10, "muN": 400, "muP": 200, "lifetimeS": 1e-6, "epsilonFcm": EPS, "qC": Q, "kJK": KB},
              "units": {"x": "um", "potential": "V", "density": "cm^-3", "current": "A"},
              "iv": iv, "xUm": x, "potentialV": potential, "electronsCm3": electrons, "holesCm3": holes,
              "netDopingCm3": nodes("NetDoping"), "equilibriumPotentialV": equilibrium,
              "checks": {"builtInExpectedV": expected, "builtInComputedV": actual,
                         "builtInErrorV": abs(expected - actual), "maxCurrentToleranceRatio": max(balance), "nodeCount": len(x)},
              "productApproved": False}
    if result["checks"]["builtInErrorV"] > 1e-7:
        raise RuntimeError("boundary-validation-failed")
    result["resultSha256"] = digest(result)
    return result

def main():
    try:
        data = strict_json(sys.stdin.buffer.read(4_194_305), maximum_bytes=4_194_304)
        profile = None
        if isinstance(data, dict) and set(data)=={"input","processProfile"}:
            profile, data = data["processProfile"], data["input"]
        if isinstance(data, dict) and "model" in data:
            from .mos_solver import solve_mos
            result = solve_mos(data, profile)
        else:
            result = solve_pn(data)
        print("OPENTCAD_RESULT=" + canonical(result).decode("ascii"), flush=True)
    except Exception:
        # Native paths and diagnostics remain private to the child process.
        print("OPENTCAD_ERROR=solver-failed", flush=True)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
