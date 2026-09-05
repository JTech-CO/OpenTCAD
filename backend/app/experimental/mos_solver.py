"""2D Poisson/drift-diffusion NMOS with an explicitly meshed gate dielectric.

The mesh and expressions are code-owned. DEVSIM supplies its Apache-2.0
simple_physics models. A separately configured SUPREM profile may replace
silicon doping; geometry is deliberately not inferred from arbitrary files.
"""
import hashlib
import math
from pathlib import Path
import platform

from .contract import digest
from .mos_contract import MODEL, validate_mos
from .solver import EPS, KB, Q, VT, load_devsim

def geometry(p):
    """Conforming triangular Si/oxide mesh in cm, no external mesher needed."""
    length, left, right = p["gateLengthUm"] + 1, .5, .5 + p["gateLengthUm"]
    refine = p["refinement"]
    def subdivide(a, b, spacing):
        count = math.ceil((b-a)/spacing - 1e-10)
        return [a + (b-a)*i/count for i in range(count)]
    xs = subdivide(0, left, .05/refine) + subdivide(left, right, .05/refine) + subdivide(right, length, .05/refine) + [length]
    ys = subdivide(0, .03, .005/refine) + subdivide(.03, .15, .02/refine) + subdivide(.15, .5, .05/refine) + [.5]
    coords, elements, lookup = [], [], {}
    names = ["silicon", "oxide", "source", "drain", "body", "gate", "interface"]
    def node(x, y):
        key = (round(x, 12), round(y, 12))
        if key not in lookup:
            lookup[key] = len(coords)//3
            coords.extend([x*1e-4, y*1e-4, 0.])
        return lookup[key]
    def rectangle(xx, yy, physical):
        for y0, y1 in zip(yy, yy[1:]):
            for x0, x1 in zip(xx, xx[1:]):
                a,b,c,d = node(x0,y0),node(x1,y0),node(x1,y1),node(x0,y1)
                elements.extend([2,physical,a,b,c,2,physical,a,c,d])
    def edge(x0,y0,x1,y1,physical):
        elements.extend([1,physical,node(x0,y0),node(x1,y1)])
    rectangle(xs, ys, 0)
    gate_x = [x for x in xs if left-1e-10 <= x <= right+1e-10]
    oxide = p["oxideNm"]*.001
    rectangle(gate_x, [-oxide, -oxide/2, 0], 1)
    for a,b in zip(xs,xs[1:]):
        edge(a,.5,b,.5,4)
        if b <= left-.099: edge(a,0,b,0,2)
        if a >= right+.099: edge(a,0,b,0,3)
    for a,b in zip(gate_x,gate_x[1:]):
        edge(a,-oxide,b,-oxide,5)
        edge(a,0,b,0,6)
    return coords, elements, names

def solve_mos(value, process_profile=None):
    p = validate_mos(value)
    if (p["dopingMode"]=="suprem") != (process_profile is not None):
        raise ValueError("mos-process-source-mismatch")
    ds = load_devsim()
    from devsim.python_packages import simple_physics as physics
    from devsim.python_packages.model_create import CreateSolution
    device, region = "mos", "silicon"
    coords, elements, names = geometry(p)
    ds.create_gmsh_mesh(mesh=device, coordinates=coords, elements=elements, physical_names=names)
    for name, material in ((region,"Silicon"),("oxide","Oxide")):
        ds.add_gmsh_region(mesh=device, gmsh_name=name, region=name, material=material)
    for name in ("source", "drain", "body", "gate"):
        ds.add_gmsh_contact(mesh=device, gmsh_name=name, region="oxide" if name=="gate" else region, name=name, material="metal")
    ds.add_gmsh_interface(mesh=device, gmsh_name="interface", region0=region, region1="oxide", name="interface")
    ds.finalize_mesh(mesh=device)
    ds.create_device(mesh=device, device=device)
    physics.SetSiliconParameters(device, region, 300)
    for name,val in {"Permittivity":EPS,"ElectronCharge":Q,"kT":KB*300,"V_t":VT,
                     "mu_n":400,"mu_p":200,"taun":1e-6,"taup":1e-6,
                     "NA":p["acceptorsCm3"],"ND":p["donorsCm3"],"left":.5e-4,
                     "right":(.5+p["gateLengthUm"])*1e-4}.items():
        ds.set_parameter(device=device, region=region, name=name, value=val)
    def nodes(name, reg=region):
        return list(ds.get_node_model_values(device=device, region=reg, name=name))
    provenance = {"kind":"analytic-template", "processSimulated":False}
    if process_profile is None:
        ds.node_model(device=device, region=region, name="NetDoping", equation="ND*(exp(-1*((max(x-left,0)/5e-6)^2))+exp(-1*((max(right-x,0)/5e-6)^2)))*exp(-1*((y/7e-6)^2))-NA")
    else:
        from .suprem import interpolate_profile
        values = interpolate_profile(process_profile, list(zip([x*1e4 for x in nodes("x")], [y*1e4 for y in nodes("y")])))
        # Importing a PN slab or an all-n region must not masquerade as NMOS.
        xs,ys=[x*1e4 for x in nodes("x")],[y*1e4 for y in nodes("y")]
        right=.5+p["gateLengthUm"]
        for x,y,n in zip(xs,ys,values):
            if abs(y-.5)<1e-9 and n>=0: raise ValueError("str-body-not-p-type")
            if abs(y)<1e-9 and (x<=.400000001 or x>=right+.099999999) and n<=0: raise ValueError("str-contact-not-n-type")
        if interpolate_profile(process_profile,[(.5+p["gateLengthUm"]/2,0)])[0]>=0:
            raise ValueError("str-channel-not-p-type")
        ds.node_solution(device=device, region=region, name="NetDoping")
        ds.set_node_values(device=device, region=region, name="NetDoping", values=values)
        provenance = {"kind":"suprem-str-import", "processSimulated":False,
                      "sourceSha256":process_profile["sourceSha256"], "transfer":"barycentric-active-doping", "geometry":"template-remesh"}
    physics.CreateSiliconPotentialOnly(device, region)
    for contact in ("source", "drain", "body"):
        ds.set_parameter(device=device, name=physics.GetContactBiasName(contact), value=0)
        physics.CreateSiliconPotentialOnlyContact(device, region, contact)
    physics.SetOxideParameters(device, "oxide", 300)
    ds.set_parameter(device=device, region="oxide", name="Permittivity", value=3.9*8.8541878128e-14)
    physics.CreateOxidePotentialOnly(device, "oxide")
    # Metal potential relative to intrinsic silicon: fixed +0.45 V offset.
    ds.set_parameter(device=device, name="gate_bias", value=.45)
    physics.CreateOxideContact(device, "oxide", "gate")
    physics.CreateSiliconOxideInterface(device, "interface")
    ds.solve(type="dc", absolute_error=1e-10, relative_error=1e-10, maximum_iterations=100)
    for name, initial in (("Electrons","IntrinsicElectrons"),("Holes","IntrinsicHoles")):
        CreateSolution(device, region, name)
        ds.set_node_values(device=device, region=region, name=name, init_from=initial)
    physics.CreateSiliconDriftDiffusion(device, region)
    for contact in ("source","drain","body"):
        physics.CreateSiliconDriftDiffusionAtContact(device, region, contact)
    def solve():
        ds.solve(type="dc", absolute_error=1e6, relative_error=1e-9, maximum_iterations=100)
    solve()
    for i in range(1, math.ceil(p["gateV"]/.05)+1):
        ds.set_parameter(device=device, name="gate_bias", value=.45+min(i*.05,p["gateV"]))
        solve()
    iv, currents, ratios = [], [], []
    steps = max(1,math.ceil(p["drainV"]/.025))
    for i in range(steps+1):
        voltage = p["drainV"]*i/steps
        ds.set_parameter(device=device, name="drain_bias", value=voltage)
        solve()
        # 2D contact integrals are A/cm of out-of-plane width.
        sample = {c:sum(ds.get_contact_current(device=device,contact=c,equation=e) for e in ("ElectronContinuityEquation","HoleContinuityEquation"))*p["widthUm"]*1e-4 for c in ("source","drain","body")}
        ratio = abs(sum(sample.values()))/(1e-13+1e-5*max(abs(v) for v in sample.values()))
        if not math.isfinite(ratio) or ratio>1: raise RuntimeError("mos-current-conservation")
        ratios.append(ratio)
        currents.append(sample)
        iv.append([voltage, sample["drain"]])
    regions = {}
    for reg in (region,"oxide"):
        data = {"xUm":[x*1e4 for x in nodes("x",reg)], "yUm":[y*1e4 for y in nodes("y",reg)],
                "triangles":[list(t) for t in ds.get_element_node_list(device=device,region=reg)], "potentialV":nodes("Potential",reg)}
        if reg==region:
            data.update(electronsCm3=nodes("Electrons"), holesCm3=nodes("Holes"), netDopingCm3=nodes("NetDoping"))
            if min(data["electronsCm3"]+data["holesCm3"])<=0: raise RuntimeError("mos-carriers")
        if any(not math.isfinite(v) for k,arr in data.items() if k!="triangles" for v in arr): raise RuntimeError("mos-nonfinite")
        regions[reg] = data
    result = {"format":"opentcad-mos-result", "schemaVersion":1, "model":MODEL, "input":p,
              "inputSha256":digest(p), "solver":"DEVSIM", "solverVersion":"2.11.0",
              "templateSha256":hashlib.sha256(b"".join((Path(__file__).parent/name).read_bytes() for name in ("mos_solver.py","mos_contract.py","suprem.py","solver.py"))).hexdigest(),
              "environment":{"python":platform.python_version(),"os":platform.system(),"machine":platform.machine()},
              "units":{"length":"um","potential":"V","density":"cm^-3","current":"A"},
              "constants":{"temperatureK":300,"gateOffsetV":.45,"muN":400,"muP":200,"niCm3":1e10},
              "dopingSource":provenance,"regions":regions,"iv":iv,"contactCurrentsA":currents,
              "checks":{"maxCurrentToleranceRatio":max(ratios),"siliconNodes":len(regions[region]["xUm"])},
              "productApproved":False}
    result["resultSha256"] = digest(result)
    return result
