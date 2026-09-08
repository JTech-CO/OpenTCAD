"""Original mesh and explicit electrode contracts; generated fixtures are synthetic."""
import asyncio
import copy
import math
import os
import unittest
from uuid import uuid4

from backend.app.experimental.contract import canonical
from backend.app.experimental.mos_contract import DEFAULT
from backend.app.experimental.mos_solver import geometry
from backend.app.experimental.suprem import parse_structure
from backend.app.experimental.process_mesh import prepare_mesh,topology,nodal_doping,validate_planarity
from backend.app.experimental.service import LaboratoryApi,run_solver
from backend.app.experimental.replay import compare

def fixture():
    xyz,elements,names=geometry(DEFAULT)
    points=[(xyz[i]*1e4,xyz[i+1]*1e4) for i in range(0,len(xyz),3)]
    lines=["v SUPREM-IV.GS B.9305","D 2 3 3","r 1 3","r 2 1"]
    lines += [f"c {i+1} {x:.17g} {y:.17g} 0" for i,(x,y) in enumerate(points)]
    contacts={name:{"region":2 if name=="gate" else 1,"edges":[]} for name in ("source","drain","body","gate")}
    silicon=set();cursor=0;identifier=1
    while cursor<len(elements):
        kind,physical=elements[cursor:cursor+2];count=3 if kind==2 else 2
        ids=[i+1 for i in elements[cursor+2:cursor+2+count]];cursor+=count+2
        if kind==2:
            lines.append(f"t {identifier} {physical+1} {' '.join(map(str,ids))} -1 -1 -1 -1 -1");identifier+=1
            if physical==0:silicon.update(ids)
        elif names[physical] in contacts:contacts[names[physical]]["edges"].append(ids)
    lines += ["s 2 20 23"]
    for i in sorted(silicon):
        x,y=points[i-1]
        n=1e18*(math.exp(-(max(x-.5,0)/.05)**2)+math.exp(-(max(1.5-x,0)/.05)**2))*math.exp(-(y/.07)**2)-1e16
        lines.append(f"n {i-1} 3 {max(n,0):.17g} {max(-n,0):.17g}")
    profile=parse_structure("\n".join(lines).encode("ascii"))
    manifest={"format":"opentcad-suprem-contacts","schemaVersion":1,"sourceSha256":profile["sourceSha256"],"contacts":contacts}
    return profile,manifest

class ProcessMeshTests(unittest.IsolatedAsyncioTestCase):
    def test_preserves_geometry_area_and_material_specific_nodal_values(self):
        profile,manifest=fixture();mesh=prepare_mesh(profile,manifest)
        self.assertAlmostEqual(mesh["areasUm2"]["silicon"],1)
        self.assertAlmostEqual(mesh["areasUm2"]["oxide"],.01)
        points={i:(x,y) for i,x,y in profile["meshSource"]["points"]}
        data=profile["meshSource"]["siliconDoping"]
        values=nodal_doping(mesh,[points[i][0]*1e-4 for i,n in data],[points[i][1]*1e-4 for i,n in data])
        self.assertEqual(values,[n for i,n in data])
        self.assertEqual(mesh,prepare_mesh(profile,copy.deepcopy(manifest)))

    def test_rejects_wrong_hash_missing_shared_internal_and_wrong_region_contacts(self):
        profile,manifest=fixture()
        cases=[]
        wrong=copy.deepcopy(manifest);wrong["sourceSha256"]="a"*64;cases.append(wrong)
        missing=copy.deepcopy(manifest);missing["contacts"]["gate"]["edges"]=[];cases.append(missing)
        shared=copy.deepcopy(manifest);shared["contacts"]["drain"]=shared["contacts"]["source"];cases.append(shared)
        region=copy.deepcopy(manifest);region["contacts"]["gate"]["region"]=1;cases.append(region)
        _,_,_,incidence,_,_=topology(profile)
        interior=next(list(edge) for edge,owners in incidence.items() if len(owners)==2)
        wrongedge=copy.deepcopy(manifest);wrongedge["contacts"]["source"]["edges"]=[interior];cases.append(wrongedge)
        for case in cases:
            with self.assertRaises(ValueError):prepare_mesh(profile,case)

    def test_rejects_crossings_tjunctions_duplicate_and_unsupported_materials(self):
        for points,edges in (({1:(0,0),2:(1,1),3:(0,1),4:(1,0)},[(1,2),(3,4)]),
                             ({1:(0,0),2:(1,0),3:(.5,0),4:(.5,1)},[(1,2),(3,4)])):
            with self.assertRaises(ValueError):validate_planarity(points,edges)
        p,m=fixture();bad=copy.deepcopy(p);bad["meshSource"]["triangles"].append(bad["meshSource"]["triangles"][0])
        with self.assertRaises(ValueError):prepare_mesh(bad,m)
        bad=copy.deepcopy(p);bad["meshSource"]["regions"][1][1]=4
        with self.assertRaises(ValueError):prepare_mesh(bad,m)

    async def test_no_mesh_admission_without_explicit_contacts_and_shared_cancellation(self):
        p,m=fixture();api=LaboratoryApi(process_profile=p)
        request={"requestId":str(uuid4()),"input":dict(DEFAULT,dopingMode="suprem-mesh")}
        self.assertEqual((await api.handle("POST","/v1/lab/jobs",canonical(request)))[0],409)
        p["deviceMesh"]=prepare_mesh(p,m)
        async def runner(value,process_profile):await asyncio.sleep(10)
        api=LaboratoryApi(runner=runner,process_profile=p)
        self.assertEqual((await api.handle("POST","/v1/lab/jobs",canonical(request)))[0],200)
        self.assertEqual((await api.handle("POST",f'/v1/lab/jobs/{request["requestId"]}/cancel',b'{}'))[1]["state"],"cancelled")
        status=(await api.handle("GET","/v1/lab/status",b''))[1]
        self.assertEqual(status["supremMeshSha256"],p["deviceMesh"]["meshSha256"])
        await api.close()

@unittest.skipUnless(os.environ.get("OPENTCAD_TEST_DEVSIM")=="1","requires explicitly installed DEVSIM")
class ProcessMeshNumericalTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_mesh_real_solve_identity_gate_response_and_replay(self):
        p,m=fixture();p["deviceMesh"]=prepare_mesh(p,m)
        inputs=dict(DEFAULT,dopingMode="suprem-mesh")
        original=await run_solver(inputs,process_profile=p)
        repeated=await run_solver(inputs,process_profile=p)
        reference=await run_solver(DEFAULT)
        self.assertTrue(compare(original,repeated)["numericallyReproduced"])
        self.assertAlmostEqual(original["iv"][-1][1]/reference["iv"][-1][1],1,places=6)
        self.assertEqual(original["meshChecks"]["triangleCounts"],p["deviceMesh"]["triangleCounts"])
        off=await run_solver(dict(inputs,gateV=0),process_profile=p)
        self.assertGreater(original["iv"][-1][1],10*abs(off["iv"][-1][1]))
        changed=copy.deepcopy(original);changed["contactSegmentsUm"]["source"][0][0][0]+=.01
        with self.assertRaises(ValueError):compare(changed,repeated)
